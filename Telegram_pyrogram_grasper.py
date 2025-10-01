from pyrogram import Client
import config

api_id = config.API_ID       # from my.telegram.org
api_hash = config.API_HASH
session_name = config.SESSION_NAME
channel = "durov"

# The first run will create "my_account.session" on disk
app = Client(session_name, api_id=api_id, api_hash=api_hash)

with app:
    me = app.get_me()
    print("✅ Logged in as:", me.first_name)

    print("\n📩 Last 5 messages from Pavel Durov channel:")
    for msg in app.get_chat_history(channel, limit=5):
        if msg.text:
            print("-", msg.text)
        else:
            print("- [Non-text message]")