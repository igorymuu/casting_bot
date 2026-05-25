import logging
from sqlalchemy import select
from aiogram import Bot
from aiogram.enums import ParseMode

from config import settings
from database.session import async_session
from database.models import Casting, Match, ActorProfile

import sys
import ssl
import aiohttp
from aiogram.client.session.aiohttp import AiohttpSession

class NoSSLSession(AiohttpSession):
    """Сессия с отключённой проверкой SSL — обходит SSL-inspection VPN."""
    async def create_session(self) -> aiohttp.ClientSession:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        connector = aiohttp.TCPConnector(ssl=ssl_ctx)
        return aiohttp.ClientSession(connector=connector, trust_env=True)

logger = logging.getLogger(__name__)

async def notify_matched_actors(casting_id: int) -> None:
    """
    Рассылает уведомления всем актерам, для которых создан Match 
    со статусом 'pending' для данного кастинга.
    """
    logger.info(f"Starting notification process for casting_id={casting_id}")
    
    session_factory = NoSSLSession() if sys.platform == "win32" else None
    bot = Bot(token=settings.BOT_TOKEN, session=session_factory)
    
    async with async_session() as session:
        # Получаем данные кастинга
        casting = await session.get(Casting, casting_id)
        if not casting:
            logger.error(f"Cannot notify: casting {casting_id} not found.")
            await bot.session.close()
            return
            
        # Получаем ожидающие уведомления матчи
        stmt = select(Match, ActorProfile).join(
            ActorProfile, Match.actor_id == ActorProfile.user_id
        ).where(
            Match.casting_id == casting_id,
            Match.status == 'pending'
        )
        
        result = await session.execute(stmt)
        matches_actors = result.all()
        
        if not matches_actors:
            logger.info(f"No pending matches to notify for casting_id={casting_id}")
            await bot.session.close()
            return
            
        success_count = 0
        
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        for match, actor in matches_actors:
            try:
                desc = casting.description or ""
                full_text = f"🎯 <b>Найден новый подходящий кастинг!</b>\n\n"
                full_text += f"<b>{casting.title}</b>\n\n"
                if desc:
                    full_text += f"{desc}\n\n"
                if casting.source_url:
                    full_text += f"🔗 <a href='{casting.source_url}'>Ссылка на источник</a>"

                lines = desc.split('\n') if desc else []
                if len(desc) > 300 or len(lines) > 5:
                    short_desc = '\n'.join(lines[:5])
                    if len(short_desc) > 300:
                        short_desc = short_desc[:300] + "..."
                    elif len(lines) > 5:
                        short_desc += "\n..."

                    short_text = f"🎯 <b>Найден новый подходящий кастинг!</b>\n\n"
                    short_text += f"<b>{casting.title}</b>\n\n"
                    short_text += f"{short_desc}"

                    kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="Подробнее", callback_data=f"cast_more_{casting.id}")],
                        [
                            InlineKeyboardButton(text="В избранное ❤️", callback_data=f"cast_fav_{casting.id}"),
                            InlineKeyboardButton(text="Не нравится ❌", callback_data=f"cast_hide_{casting.id}")
                        ]
                    ])
                    text_to_send = short_text
                else:
                    kb = InlineKeyboardMarkup(inline_keyboard=[
                        [
                            InlineKeyboardButton(text="В избранное ❤️", callback_data=f"cast_fav_{casting.id}"),
                            InlineKeyboardButton(text="Не нравится ❌", callback_data=f"cast_hide_{casting.id}")
                        ]
                    ])
                    text_to_send = full_text

                await bot.send_message(
                    chat_id=actor.user_id,
                    text=text_to_send,
                    parse_mode=ParseMode.HTML,
                    reply_markup=kb,
                    disable_web_page_preview=True
                )
                match.status = 'notified'
                success_count += 1
            except Exception as e:
                logger.error(f"Failed to send notification to actor={actor.user_id}: {e}")
                match.status = 'error'
                
        await session.commit()
        logger.info(f"Successfully notified {success_count} actors for casting_id={casting_id}")
        
    await bot.session.close()
