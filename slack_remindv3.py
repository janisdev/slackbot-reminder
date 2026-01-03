import os
import sys
import json
import time
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
                # Svarīgi: Bots var lasīt tikai tos kanālus, kuros tas ir biedrs ('is_member': True)
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
    hashtag = config.get("TARGET_HASHTAG", "#svarigi")
    base_message = config.get("REMINDER_MESSAGE", "Sveiks! Pamanīju, ka neesi reaģējis uz šīm svarīgajām ziņām:")

    if not token:
        print("KĻŪDA: Trūkst SLACK_BOT_TOKEN konfigurācijas failā.")
        sys.exit(1)

    client = WebClient(token=token)
    
    # 1. Iegūstam visus kanālus, kuros bots piedalās
    print(f"--- Sāku darbu ---")
    print("Meklēju kanālus...")
    channels = get_all_channels(client)
    print(f"✅ Bots atrast {len(channels)} kanālos, kuros tas ir dalībnieks.")

    # Globālais saraksts: { user_id: [ "Message 1", "Message 2" ] }
    all_users_pending_items = {}

    # 2. Ejam cauri katram kanālam
    for channel in channels:
        channel_id = channel['id']
        channel_name = channel['name']
        print(f"🔍 Pārbaudu kanālu #{channel_name}...")

        try:
            # Iegūstam pēdējās 50 ziņas
            history = client.conversations_history(channel=channel_id, limit=50)
            messages = history['messages']

            # Atrodam ziņas ar tēmturi
            target_messages = [m for m in messages if hashtag in m.get('text', '')]

            if not target_messages:
                continue # Ja nav svarīgu ziņu, ejam uz nākamo kanālu

            # Iegūstam kanāla dalībniekus (lai netraucētu cilvēkus, kas nav šajā kanālā)
            channel_member_ids = get_channel_members(client, channel_id)

            for msg in target_messages:
                raw_text = msg.get('text', 'Ziņa bez teksta')
                preview_text = format_message_preview(raw_text)
                
                # Iegūstam saiti
                try:
                    permalink_res = client.chat_getPermalink(channel=channel_id, message_ts=msg['ts'])
                    permalink = permalink_res['permalink']
                except SlackApiError:
                    permalink = "#"

                # Iegūstam, kas jau ir reaģējuši
                reacted_ids = set()
                if 'reactions' in msg:
                    for reaction in msg['reactions']:
                        for uid in reaction['users']:
                            reacted_ids.add(uid)

                # Formatējam ierakstu (pievienojam kanāla nosaukumu)
                list_item = f"• [#{channel_name}] *{preview_text}*\n   👉 {permalink}"

                # Pārbaudām, kurš nav reaģējis
                for member_id in channel_member_ids:
                    # Izlaižam botu (USLACKBOT) un tos, kas reaģējuši
                    if member_id == "USLACKBOT" or member_id in reacted_ids:
                        continue
                    
                    # Pievienojam globālajam sarakstam
                    if member_id not in all_users_pending_items:
                        all_users_pending_items[member_id] = []
                    
                    all_users_pending_items[member_id].append(list_item)

        except SlackApiError as e:
            print(f"⚠️ Kļūda apstrādājot kanālu {channel_name}: {e.response['error']}")

    # 3. Sūtam apkopotās ziņas lietotājiem
    print(f"--- Sūtu atgādinājumus ---")
    sent_count = 0
    
    for member_id, items in all_users_pending_items.items():
        # Papildus pārbaude, vai tas nav bots (lai samazinātu API izsaukumus iepriekš)
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
            
            # Neliela pauze, lai nepārslogotu API (rate limits)
            time.sleep(0.5) 

        except SlackApiError as e:
            print(f"⚠️ Nevarēja nosūtīt ziņu lietotājam {member_id}: {e.response['error']}")

    print(f"--- Pabeigts. Nosūtīti {sent_count} atgādinājumi. ---")

if __name__ == "__main__":
    main()