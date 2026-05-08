import os
import sys
import json
import time
import argparse
import re
from datetime import datetime
import unicodedata
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

CONFIG_FILE = "config.json"

stdout_reconfigure = getattr(sys.stdout, "reconfigure", None)
stderr_reconfigure = getattr(sys.stderr, "reconfigure", None)
if callable(stdout_reconfigure):
    stdout_reconfigure(encoding="utf-8", errors="replace")
if callable(stderr_reconfigure):
    stderr_reconfigure(encoding="utf-8", errors="replace")

def load_config():
    if not os.path.exists(CONFIG_FILE):
        print(f"KĻŪDA: Fails '{CONFIG_FILE}' netika atrasts!")
        sys.exit(1)
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        print(f"KĻŪDA: '{CONFIG_FILE}' nav derīgs JSON.")
        sys.exit(1)

def normalize_text(text):
    if not text:
        return ""
    text = text.lower()
    normalized = unicodedata.normalize('NFD', text)
    return "".join(c for c in normalized if unicodedata.category(c) != 'Mn')

def format_message_preview(text, length=60):
    lines = text.splitlines()
    non_quoted_lines = [line for line in lines if not re.match(r"^\s*>+", line)]
    clean_text = " ".join(non_quoted_lines).strip()
    clean_text = re.sub(r"https?://\S+", "[links]", clean_text)
    clean_text = re.sub(r"www\.\S+", "[links]", clean_text)
    clean_text = re.sub(r"\s+", " ", clean_text).strip()
    if len(clean_text) > length:
        return clean_text[:length] + "..."
    return clean_text

def get_all_channels(client):
    channels = []
    cursor = None
    try:
        while True:
            response = client.conversations_list(
                types="public_channel,private_channel",
                cursor=cursor,
                limit=100
            )
            for channel in response['channels']:
                if channel['is_member']: 
                    channels.append(channel)
            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor: break
    except SlackApiError as e:
        print(f"Kļūda iegūstot kanālus: {e}")
    return channels

def get_channel_members(client, channel_id):
    human_members = set()
    cursor = None
    try:
        while True:
            response = client.conversations_members(channel=channel_id, cursor=cursor, limit=1000)
            for member_id in response['members']:
                human_members.add(member_id)
            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor: break
    except SlackApiError as e:
        print(f"Kļūda iegūstot dalībniekus kanālam {channel_id}: {e}")
    return human_members

def run_once(config, dry_run=False):
    token = config.get("SLACK_BOT_TOKEN")
    configured_channel_id = config.get("CHANNEL_ID")
    test_recipients = set(config.get("TEST_RECIPIENTS", []))
    ignore_users = config.get("IGNORE_USERS", [])
    raw_hashtag = config.get("TARGET_HASHTAG", "#svarigi")
    search_hashtag = normalize_text(raw_hashtag)
    base_message = config.get("REMINDER_MESSAGE", "Sveiks! Pamanīju, ka neesi reaģējis uz šīm svarīgajām ziņām:")

    if not token:
        print("KĻŪDA: Trūkst SLACK_BOT_TOKEN konfigurācijas failā.")
        sys.exit(1)

    client = WebClient(token=token)
    
    print(f"--- Darbs uzsākts {time.strftime('%Y-%m-%d %H:%M:%S')} ---")
    print(f"Meklēju: '{search_hashtag}'")
    
    channels = get_all_channels(client)
    if configured_channel_id:
        channels = [ch for ch in channels if ch.get("id") == configured_channel_id]
        if not channels:
            print(f"KLUDA: CHANNEL_ID '{configured_channel_id}' netika atrasts vai bots nav saja kanala.")
            return
    print(f"✅ Bots ir {len(channels)} kanālos.")

    all_users_pending_items = {}

    for channel in channels:
        channel_id = channel['id']
        channel_name = channel['name']
        print(f"🔍 Pārbaudu #{channel_name}...")

        try:
            # Iegūstam pēdējās 50 ziņas
            history = client.conversations_history(channel=channel_id, limit=50)
            
            target_messages = [
                m for m in history['messages'] 
                if search_hashtag in normalize_text(m.get('text', ''))
            ]

            if not target_messages:
                continue 

            channel_member_ids = get_channel_members(client, channel_id)

            for msg in target_messages:
                ts = msg['ts']
                preview = format_message_preview(msg.get('text', ''))
                
                # Iegūstam linku uz ziņu
                try:
                    permalink = client.chat_getPermalink(channel=channel_id, message_ts=ts)['permalink']
                except:
                    permalink = "#"

                # Kas jau ir reaģējuši?
                reacted_ids = set()
                if 'reactions' in msg:
                    for r in msg['reactions']:
                        for uid in r['users']:
                            reacted_ids.add(uid)

                list_item = f"• *{preview}*\n   👉 {permalink}"

                for member_id in channel_member_ids:
                    # Filtri: bots, pats autors (pēc izvēles), jau reaģējis vai ignore sarakstā
                    if member_id == "USLACKBOT" or member_id in reacted_ids or member_id in ignore_users:
                        continue
                    
                    if member_id not in all_users_pending_items:
                        all_users_pending_items[member_id] = {}
                    if channel_name not in all_users_pending_items[member_id]:
                        all_users_pending_items[member_id][channel_name] = []
                    all_users_pending_items[member_id][channel_name].append(list_item)

        except SlackApiError as e:
            print(f"⚠️ Kļūda kanālā {channel_name}: {e.response['error']}")

    print(f"--- Sūtu atgādinājumus ---")
    sent_count = 0
    
    for member_id, channels_map in all_users_pending_items.items():
        if test_recipients and member_id not in test_recipients:
            continue
        try:
            user_label = member_id
            try:
                user_info = client.users_info(user=member_id)
                user = user_info.get("user", {})
                real_name = user.get("real_name") or user.get("name")
                if real_name:
                    user_label = f"{real_name} ({member_id})"
            except SlackApiError:
                pass

            grouped_parts = []
            for channel_name in sorted(channels_map.keys()):
                channel_items = channels_map[channel_name]
                channel_block = f"*#{channel_name}*\n" + "\n".join(channel_items)
                grouped_parts.append(channel_block)

            items_text = "\n\n".join(grouped_parts)
            final_message = f"{base_message}\n\n{items_text}"

            if dry_run:
                total_items = sum(len(v) for v in channels_map.values())
                print(f"🧪 DRY RUN: {user_label} saņemtu {total_items} ierakstus {len(channels_map)} čatos")
            else:
                total_items = sum(len(v) for v in channels_map.values())
                print(f"📩 Sūtu {total_items} ziņas lietotājam {user_label} ({len(channels_map)} čati)")
                client.chat_postMessage(
                    channel=member_id,
                    text=final_message,
                    mrkdwn=True,
                    unfurl_links=False,
                    unfurl_media=False,
                )
                sent_count += 1
            
            # Droša pauze, lai neizsauktu Rate Limit (1 ziņa sekundē ir droši)
            time.sleep(1.2) 

        except SlackApiError as e:
            if e.response["error"] == "ratelimited":
                retry_after = int(e.response.headers.get("Retry-After", 10))
                print(f"⏳ Rate limit! Gaidām {retry_after}s...")
                time.sleep(retry_after)
            else:
                print(f"⚠️ Nevarēja nosūtīt {member_id}: {e.response['error']}")

    if dry_run:
        print("--- DRY RUN pabeigts. Ziņas netika nosūtītas. ---")
    else:
        print(f"--- Pabeigts. Nosūtīti {sent_count} atgādinājumi. ---")


def parse_run_times(config):
    times_list = config.get("RUN_TIMES", ["08:00", "14:00"])
    valid = []
    for item in times_list:
        try:
            hh, mm = item.split(":")
            h = int(hh)
            m = int(mm)
            if 0 <= h <= 23 and 0 <= m <= 59:
                valid.append((h, m))
        except Exception:
            continue
    if not valid:
        valid = [(8, 0), (14, 0)]
    return valid


def sleep_until_next_minute():
    now = datetime.now()
    remaining = 60 - now.second
    time.sleep(max(1, remaining))


def main():
    parser = argparse.ArgumentParser(description="Slack atgādinājumu bots lokālai palaišanai")
    parser.add_argument("--daemon", action="store_true", help="Darbināt nepārtraukti pēc grafika")
    parser.add_argument("--dry-run", action="store_true", help="Nesūtīt DM, tikai parādīt kam tiktu sūtīts")
    args = parser.parse_args()

    config = load_config()

    if not args.daemon:
        run_once(config, dry_run=args.dry_run)
        return

    run_times = parse_run_times(config)
    last_run_key = None
    print("--- Daemon režīms ieslēgts ---")
    print("Izpildes laiki (lokālais laiks): " + ", ".join(f"{h:02d}:{m:02d}" for h, m in run_times))

    while True:
        now = datetime.now()
        run_key = (now.year, now.month, now.day, now.hour, now.minute)
        should_run = any(now.hour == h and now.minute == m for h, m in run_times)

        if should_run and run_key != last_run_key:
            run_once(config, dry_run=args.dry_run)
            last_run_key = run_key

        sleep_until_next_minute()

if __name__ == "__main__":
    main()
