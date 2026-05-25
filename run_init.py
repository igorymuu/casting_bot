import asyncio
from database.models import Base
from database.session import engine

async def init():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Tables created/updated")
    await engine.dispose()

asyncio.run(init())
