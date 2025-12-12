import os
import sys
import json
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

CONFIG_FILE = "config.json"

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

def format_message_preview(text, length=60):
    """Palīgfunkcija, kas noīsina tekstu un noņem jaunas rindas."""
    # Aizvietojam 'enter' ar atstarpēm, lai saraksts būtu kompakts
    clean_text = text.replace('\n', ' ').strip()
    if len(clean_text) > length:
        return clean_text[:length] + "..."
    return clean_text

def main():
    config = load_config()
    token = config.get("SLACK_BOT_TOKEN")
    channel_id = config.get("CHANNEL_ID")
    hashtag = config.get("TARGET_HASHTAG", "#svarigi")
    base_message = config.get("REMINDER_MESSAGE", "Sveiks! Pamanīju, ka neesi reaģējis uz šīm svarīgajām ziņām:")

    if not token or not channel_id:
        print("KĻŪDA: Trūkst token vai channel_id.")
        sys.exit(1)

    client = WebClient(token=token)

    try:
        print(f"--- Sāku darbu ---")
        print(f"Meklēju ziņas ar '{hashtag}' kanālā {channel_id}...")

        history = client.conversations_history(channel=channel_id, limit=50)
        messages = history['messages']

        target_messages = []
        for msg in messages:
            if hashtag in msg.get('text', ''):
                target_messages.append(msg)
        
        if not target_messages:
            print(f"❌ Neviena ziņa ar '{hashtag}' netika atrasta.")
            return

        print(f"✅ Atrastas {len(target_messages)} ziņas.")

        # Iegūstam dalībniekus
        members_response = client.conversations_members(channel=channel_id, limit=1000)
        all_member_ids = members_response['members']
        
        human_members = []
        for member_id in all_member_ids:
            try:
                user_info = client.users_info(user=member_id)
                user = user_info['user']
                if not (user.get('is_bot') or user.get('deleted') or member_id == "USLACKBOT"):
                    human_members.append(member_id)
            except SlackApiError:
                continue

        # Apkopojam datus
        user_pending_items = {uid: [] for uid in human_members}

        for msg in target_messages:
            # 1. Iegūstam un noformējam tekstu
            raw_text = msg.get('text', 'Ziņa bez teksta')
            preview_text = format_message_preview(raw_text)

            # 2. Iegūstam saiti
            try:
                permalink_res = client.chat_getPermalink(channel=channel_id, message_ts=msg['ts'])
                permalink = permalink_res['permalink']
            except SlackApiError:
                permalink = ""

            # 3. Iegūstam reaģētājus
            reacted_ids = set()
            if 'reactions' in msg:
                for reaction in msg['reactions']:
                    for uid in reaction['users']:
                        reacted_ids.add(uid)

            # 4. Pievienojam sarakstam tiem, kas nav reaģējuši
            # Izveidojam smuku ierakstu priekš saraksta
            list_item = f"• *{preview_text}*\n   👉 {permalink}"

            for member_id in human_members:
                if member_id not in reacted_ids:
                    user_pending_items[member_id].append(list_item)

        # Sūtam ziņas
        sent_count = 0
        for member_id, items in user_pending_items.items():
            if not items:
                continue

            # Saliekam visu kopā vienā tekstā
            items_text = "\n\n".join(items) # Divas rindstarpas, lai atdalītu ierakstus
            final_message = f"{base_message}\n\n{items_text}"

            try:
                user_info = client.users_info(user=member_id)
                real_name = user_info['user'].get('real_name', member_id)
                print(f"📩 Sūtu {len(items)} ziņas: {real_name}")
                
                client.chat_postMessage(
                    channel=member_id,
                    text=final_message
                )
                sent_count += 1
            except SlackApiError as e:
                print(f"⚠️ Kļūda lietotājam {member_id}: {e.response['error']}")

        print(f"--- Pabeigts. Nosūtīti {sent_count} atgādinājumi. ---")

    except SlackApiError as e:
        print(f"🔥 API Kļūda: {e.response['error']}")

if __name__ == "__main__":
    main()