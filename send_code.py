
import asyncio
from pyrogram import Client
from config import settings

async def send_code():
    app = Client('casting_userbot', api_id=settings.API_ID, api_hash=settings.API_HASH, phone_number=settings.PHONE_NUMBER)
    await app.connect()
    try:
        sc = await app.send_code(settings.PHONE_NUMBER)
        with open('hash.txt', 'w') as f:
            f.write(sc.phone_code_hash)
        print("HASH_READY")
    except Exception as e:
        print("ERROR:", e)
    finally:
        await app.disconnect()

asyncio.run(send_code())
