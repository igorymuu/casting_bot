import asyncio
import logging
import ssl
import sys

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

from config import settings
from database.session import async_session
from bot.middlewares.db import DbSessionMiddleware
from bot.handlers import base, profile, cabinet, admin

class NoSSLSession(AiohttpSession):
    async def create_session(self) -> aiohttp.ClientSession:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        connector = aiohttp.TCPConnector(ssl=ssl_ctx)
        return aiohttp.ClientSession(connector=connector, trust_env=True)

async def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)

    # Использовать NoSSLSession только на Windows
    session = NoSSLSession() if sys.platform == "win32" else AiohttpSession()

    bot = Bot(
        token=settings.BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    dp.update.middleware(DbSessionMiddleware(session_pool=async_session))

    dp.include_router(base.router)
    dp.include_router(profile.router)
    dp.include_router(cabinet.router)
    dp.include_router(admin.router)

    from parser.userbot import start_userbot
    asyncio.create_task(start_userbot())

    from aiogram.types import BotCommand, MenuButtonCommands

    await bot.delete_webhook(drop_pending_updates=True)

    # Регистрируем команды бота (кнопка Меню в Telegram)
    await bot.set_my_commands([
        BotCommand(command="start", description="🏠 Главное меню"),
        BotCommand(command="lk",    description="📂 Личный кабинет"),
    ])
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())

    await dp.start_polling(bot)

if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())

