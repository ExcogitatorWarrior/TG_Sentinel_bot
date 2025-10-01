from pyrogram import Client
import requests
import asyncio
import config

SESSION_NAME = config.SESSION_NAME
API_ID = config.API_ID       # from my.telegram.org
API_HASH = config.API_HASH
CHANNEL_LINK = config.CHANNEL_LINK

async def get_chat_id():
    async with Client(SESSION_NAME, API_ID, API_HASH) as app:
        chat = await app.get_chat(CHANNEL_LINK)
        print("Chat ID:", chat.id)          # Numeric ID you can use
        print("Chat title:", chat.title)    # Optional, for verification
        return chat.id

asyncio.run(get_chat_id())