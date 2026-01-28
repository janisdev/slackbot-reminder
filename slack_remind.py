import os
import sys
import json
import time
import unicodedata  # <--- JAUNS: Nepieciešams teksta attīrīšanai
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

def normalize_text(text):
    """
    Pārvērš tekstu uz mazajiem burtiem un noņem diakritiskās zīmes (garumzīmes/mīkstinājumus).
    Piemēram: '#Svarīgi' -> '#svarigi'
    """
    if not text:
        return ""
    # 1. Uz mazajiem burtiem
    text = text.lower()
    # 2. Sadalām unicode simbolus (piem. 'ā' -> 'a' + 'macron')
    normalized = unicodedata.normalize('NFD', text)
    # 3. Atmetam visas 'ne-burtu' zīmes (kategorija Mn - Mark, nonspacing)
    return "".join(c for c in normalized if unicodedata.category(c) != 'Mn')

def format_message_preview(text, length=60):
    """Palīgfunkcija, kas noīsina tekstu un noņem jaunas rindas."""
    clean_text = text.replace('\n', ' ').strip()
    if len(clean_text) > length:
        return clean_text[:length] + "..."
    return clean_text

def get_all_channels(client):
    """Iegūst sarakstu ar visiem kanāliem, kuros bots ir biedrs."""
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
            if not cursor:
                break
    except SlackApiError as e:
        print(f"Kļūda iegūstot kanālus: {e}")
    return channels

def get_channel_members(client, channel_id):
    """Iegūst visus cilvēkus (ne-botus) konkrētā kanālā."""
    human_members = set()
    cursor = None
    try:
        while True:
            response = client.conversations_members(channel=channel_id, cursor=cursor, limit=1000)
            for member_id in response['members']:
                human_members.add(member_id)
            
            cursor = response.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
    except SlackApiError as e:
        print(f"Kļūda iegūstot dalībniekus kanālam {channel_id}: {e}")
    
    return human_members

def main():
    config = load_config()
    token = config.get("SLACK_BOT_TOKEN")
    
    # Ielādējam ignorējamo lietotāju sarakstu
    # Ja saraksta nav, izmantojam tukšu sarakstu
    ignore_users = config.get("IGNORE_USERS", [])
    
    raw_hashtag = config.get("TARGET_HASHTAG", "#svarigi")
    search_hashtag = normalize_text(raw_hashtag)
    
    base_message = config.get("REMINDER_MESSAGE", "Sveiks! Pamanīju, ka neesi reaģējis uz šīm svarīgajām ziņām:")

    if not token:
        print("KĻŪDA: Trūkst SLACK_BOT_TOKEN konfigurācijas failā.")
        sys.exit(1)

    client = WebClient(token=token)
    
    print(f"--- Sāku darbu ---")
    print(f"Meklēju ziņas ar tēmturi (normalizēts): '{search_hashtag}'")
    
    channels = get_all_channels(client)
    print(f"✅ Bots atrast {len(channels)} kanālos, kuros tas ir dalībnieks.")

    all_users_pending_items = {}

    for channel in channels:
        channel_id = channel['id']
        channel_name = channel['name']
        print(f"🔍 Pārbaudu kanālu #{channel_name}...")

        try:
            history = client.conversations_history(channel=channel_id, limit=50)
            messages = history['messages']

            target_messages = []
            for m in messages:
                raw_text = m.get('text', '')
                if search_hashtag in normalize_text(raw_text):
                    target_messages.append(m)

            if not target_messages:
                continue 

            channel_member_ids = get_channel_members(client, channel_id)

            for msg in target_messages:
                raw_text = msg.get('text', 'Ziņa bez teksta')
                preview_text = format_message_preview(raw_text)
                
                try:
                    permalink_res = client.chat_getPermalink(channel=channel_id, message_ts=msg['ts'])
                    permalink = permalink_res['permalink']
                except SlackApiError:
                    permalink = "#"

                reacted_ids = set()
                if 'reactions' in msg:
                    for reaction in msg['reactions']:
                        for uid in reaction['users']:
                            reacted_ids.add(uid)

                list_item = f"• [#{channel_name}] *{preview_text}*\n   👉 {permalink}"

                for member_id in channel_member_ids:
                    # Pārbaude: Vai lietotājs ir bots, vai jau reaģējis, VAI ir "ignore" sarakstā
                    if member_id == "USLACKBOT" or member_id in reacted_ids:
                        continue
                    
                    # JAUNS: Pārbaude pret config faila sarakstu
                    if member_id in ignore_users:
                        # Debugam var atstāt, lai redzētu, ka tiek ignorēts
                        # print(f"Izlaižu ignorēto aģentu: {member_id}")
                        continue
                    
                    if member_id not in all_users_pending_items:
                        all_users_pending_items[member_id] = []
                    
                    all_users_pending_items[member_id].append(list_item)

        except SlackApiError as e:
            print(f"⚠️ Kļūda apstrādājot kanālu {channel_name}: {e.response['error']}")

    print(f"--- Sūtu atgādinājumus ---")
    sent_count = 0
    
    for member_id, items in all_users_pending_items.items():
        # Papildu drošība: pārbaudām arī šeit, ja nu kāds ID iekļuvis sarakstā citādi
        if member_id in ignore_users:
            print(f"🚫 Izlaižu lietotāju {member_id} (atrodas IGNORE_USERS sarakstā).")
            continue

        try:
            user_info = client.users_info(user=member_id)
            user = user_info['user']
            if user.get('is_bot') or user.get('deleted'):
                continue
            
            real_name = user.get('real_name', member_id)
            
            items_text = "\n\n".join(items)
            final_message = f"{base_message}\n\n{items_text}"

            print(f"📩 Sūtu {len(items)} ziņas: {real_name}")
            client.chat_postMessage(channel=member_id, text=final_message)
            sent_count += 1
            
            time.sleep(0.5) 

        except SlackApiError as e:
            print(f"⚠️ Nevarēja nosūtīt ziņu lietotājam {member_id}: {e.response['error']}")

    print(f"--- Pabeigts. Nosūtīti {sent_count} atgādinājumi. ---")

if __name__ == "__main__":
    main()