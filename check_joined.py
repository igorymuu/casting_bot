import asyncio
from pyrogram import Client
from config import settings

async def check():
    channels = ['tfp_commerce', 'castings', 'Kastingi7', 'casting_msk', 'castgcd', 'om_cast', 'test_Neyron']
    app = Client("casting_userbot_check", api_id=settings.API_ID, api_hash=settings.API_HASH,
                 phone_number=settings.PHONE_NUMBER, workdir="/app")
    await app.start()
    for ch in channels:
        try:
            chat = await app.get_chat(ch)
            print(f"OK @{ch} title={chat.title}")
        except Exception as e:
            print(f"ERR @{ch}: {e}")
    await app.stop()

asyncio.run(check())

