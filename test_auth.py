
import asyncio
from pyrogram import Client
from config import settings
async def test():
    app = Client('casting_userbot', api_id=settings.API_ID, api_hash=settings.API_HASH)
    print("starting...")
    try:
        await app.start()
        print("start ok")
        me = await app.get_me()
        print("get_me ok", me.id)
        await app.stop()
        print("SUCCESS_OK")
    except Exception as e:
        print("ERROR:", e)

asyncio.run(test())
