import asyncio, logging, os
from pyrogram import Client, filters
from pyrogram.enums import ChatType
from pyrogram.handlers import MessageHandler
from sqlalchemy import select
from config import settings
from parser.service import process_new_casting

logger = logging.getLogger(__name__)
app = None
_listening_ids: set = set()
_bot_ready = False

DEFAULT_CHANNELS = ["tfp_commerce", "castings", "Kastingi7", "casting_msk", "castgcd", "om_cast"]


async def _ensure_db_ready():
    """Создаёт недостающие таблицы и сеет каналы, если таблица пуста."""
    try:
        from database.session import engine
        from database.models import Base
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("DB tables ensured")

        from database.session import async_session
        from database.models import ParsedChannel
        async with async_session() as s:
            count = await s.scalar(
                select(ParsedChannel.id).where(ParsedChannel.is_active == True)
            )
            if count is None:
                for ch in DEFAULT_CHANNELS:
                    s.add(ParsedChannel(username=ch, title=ch, is_active=True))
                await s.commit()
                logger.info(f"Seeded {len(DEFAULT_CHANNELS)} default channels into DB")
    except Exception as e:
        logger.error(f"DB init failed: {e}")


async def _load_active_channels():
    """Возвращает список (username, chat_id_or_None) активных каналов из БД."""
    try:
        from database.session import async_session
        from database.models import ParsedChannel
        async with async_session() as s:
            res = await s.execute(
                select(ParsedChannel.username, ParsedChannel.chat_id)
                .where(ParsedChannel.is_active == True)
            )
            rows = res.all()
            logger.info(f"Loaded {len(rows)} channels from DB")
            return [(r[0], r[1]) for r in rows]
    except Exception as e:
        logger.error(f"DB load failed, fallback: {e}")
        return [(ch, None) for ch in DEFAULT_CHANNELS]


async def _save_chat_id(username: str, chat_id: int):
    """Сохраняет chat_id в БД для быстрого старта в следующий раз."""
    try:
        from database.session import async_session
        from database.models import ParsedChannel
        from sqlalchemy import update
        async with async_session() as s:
            await s.execute(
                update(ParsedChannel)
                .where(ParsedChannel.username == username)
                .values(chat_id=chat_id)
            )
            await s.commit()
    except Exception as e:
        logger.warning(f"Could not save chat_id for @{username}: {e}")


async def _join_and_resolve_bg(client, channels):
    """Background task: join channels one by one with flood-wait handling.
    channels: list of (username, cached_chat_id_or_None)
    Adds resolved chat_ids to _listening_ids as it goes."""
    global _listening_ids, _bot_ready
    for ch, cached_id in channels:
        is_private = ch.startswith("+")
        try:
            if is_private:
                try:
                    chat = await client.join_chat(f"https://t.me/{ch}")
                    _listening_ids.add(chat.id)
                    logger.info(f"Joined private @{ch} (id={chat.id})")
                    await _save_chat_id(ch, chat.id)
                    await asyncio.sleep(3)
                except Exception as je:
                    je_str = str(je)
                    if "FLOOD_WAIT" in je_str:
                        wait = _parse_flood_wait(je_str)
                        logger.warning(f"FLOOD_WAIT joining private @{ch}, waiting {wait}s...")
                        await asyncio.sleep(wait)
                        try:
                            chat = await client.join_chat(f"https://t.me/{ch}")
                            _listening_ids.add(chat.id)
                            await _save_chat_id(ch, chat.id)
                            logger.info(f"Joined private @{ch} after wait (id={chat.id})")
                        except Exception as je2:
                            je2_str = str(je2)
                            if "USER_ALREADY_PARTICIPANT" in je2_str or "already" in je2_str.lower():
                                try:
                                    chat = await client.get_chat(f"https://t.me/{ch}")
                                    _listening_ids.add(chat.id)
                                    if not cached_id:
                                        await _save_chat_id(ch, chat.id)
                                    logger.info(f"Already in private @{ch} after wait (id={chat.id})")
                                except Exception as ge:
                                    logger.warning(f"Cannot get private channel {ch} after wait: {ge}")
                            else:
                                logger.warning(f"Still cannot join private @{ch} after wait: {je2}")
                    elif "USER_ALREADY_PARTICIPANT" in je_str or "already" in je_str.lower():
                        try:
                            chat = await client.get_chat(f"https://t.me/{ch}")
                            _listening_ids.add(chat.id)
                            if not cached_id:
                                await _save_chat_id(ch, chat.id)
                            logger.info(f"Already in private @{ch} (id={chat.id})")
                        except Exception as ge:
                            logger.warning(f"Cannot get private channel {ch}: {ge}")
                    elif "INVITE_REQUEST_SENT" in je_str:
                        logger.warning(f"Join request sent for private @{ch} (approval needed)")
                    else:
                        logger.warning(f"Cannot join private @{ch}: {je}")
            else:
                try:
                    chat = await client.get_chat(ch)
                    chat_id = chat.id
                    # Для каналов join_chat безопасно вызвать — если уже подписаны,
                    # вернёт Chat без ошибки (или USER_ALREADY_PARTICIPANT).
                    try:
                        await client.join_chat(ch)
                        logger.info(f"Joined @{ch} (id={chat_id})")
                        await asyncio.sleep(3)
                    except Exception as je:
                        je_str = str(je)
                        if "USER_ALREADY_PARTICIPANT" in je_str or "already" in je_str.lower():
                            logger.info(f"Already in @{ch} (id={chat_id})")
                        elif "FLOOD_WAIT" in je_str:
                            wait = _parse_flood_wait(je_str)
                            logger.warning(f"FLOOD_WAIT joining @{ch}, waiting {wait}s...")
                            await asyncio.sleep(wait)
                            try:
                                await client.join_chat(ch)
                                logger.info(f"Joined @{ch} after wait (id={chat_id})")
                            except Exception as je2:
                                logger.warning(f"Still cannot join @{ch} after wait: {je2}")
                        else:
                            logger.warning(f"Cannot join @{ch}: {je}")
                    _listening_ids.add(chat_id)
                    if not cached_id:
                        await _save_chat_id(ch, chat_id)
                    await asyncio.sleep(2)
                except Exception as e:
                    e_str = str(e)
                    if "FLOOD_WAIT" in e_str:
                        wait = _parse_flood_wait(e_str)
                        logger.warning(f"FLOOD_WAIT resolving @{ch}, waiting {wait}s...")
                        await asyncio.sleep(wait)
                        try:
                            chat = await client.get_chat(ch)
                            chat_id = chat.id
                            _listening_ids.add(chat_id)
                            if not cached_id:
                                await _save_chat_id(ch, chat_id)
                            logger.info(f"Resolved @{ch} after wait (id={chat_id})")
                        except Exception as e2:
                            logger.warning(f"Still cannot resolve @{ch} after wait: {e2}")
                    elif "USERNAME_NOT_OCCUPIED" in e_str or "USERNAME_INVALID" in e_str or "not found" in e_str.lower():
                        logger.warning(f"@{ch} does not exist, marking inactive in DB")
                        await _mark_channel_inactive(ch)
                    else:
                        logger.warning(f"Cannot access @{ch}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error processing @{ch}: {e}")

    _bot_ready = True
    logger.info("Background join complete. Listening to %d channels.", len(_listening_ids))


def _parse_flood_wait(error_str: str) -> int:
    """Extract wait seconds from FLOOD_WAIT error string."""
    import re
    m = re.search(r"wait of (\d+) seconds", error_str)
    if m:
        return int(m.group(1))
    m = re.search(r"FLOOD_WAIT_(\d+)", error_str)
    if m:
        return int(m.group(1))
    return 30


async def _mark_channel_inactive(username: str):
    try:
        from database.session import async_session
        from database.models import ParsedChannel
        from sqlalchemy import update
        async with async_session() as s:
            await s.execute(
                update(ParsedChannel)
                .where(ParsedChannel.username == username)
                .values(is_active=False)
            )
            await s.commit()
            logger.info(f"Marked @{username} as inactive in DB")
    except Exception as e:
        logger.error(f"Failed to mark @{username} inactive: {e}")

CASTING_KEYWORDS = [
    "кастинг", "casting", "ищем", "требуется", "нужен", "нужна", "нужны",
    "актёр", "актер", "актриса", "актрис", "модель", "модели",
    "съёмки", "съемки", "съемка", "роль", "роли",
    "возраст", "лет", "пол", "мужчина", "женщина",
    "гонорар", "оплата", "ставка", "смена", "тфп", "tfp",
    "аудиция", "пробы", "проба", "фотопробы",
    "реклама", "клип", "сериал", "фильм", "спектакль", "театр",
    "массовка", "амс", "ams",
]

def _is_casting(text: str) -> bool:
    """Пропускаем всё — LLM сама отсеет не-кастинги"""
    return True

async def new_channel_message(client, message):
    global _listening_ids
    if message.chat.type not in (ChatType.CHANNEL,):
        return
    chat_id = message.chat.id
    if _listening_ids and chat_id not in _listening_ids:
        return
    url = f"https://t.me/{message.chat.username}/{message.id}" if message.chat.username else f"https://t.me/c/{str(chat_id).replace('-100', '')}/{message.id}"
    logger.info(f"Message from {message.chat.username or chat_id}: {(message.text or '')[:60]}")
    text = message.text or message.caption
    logger.info(f"RAW from chat_id={chat_id} @{message.chat.username}: {(text or '')[:120]}")
    if text:
        if not _is_casting(text):
            logger.debug(f"Skipped (not a casting): {text[:80]!r}")
            return
        asyncio.create_task(process_new_casting(text=text, source_url=url))

async def _poll_channels(client):
    """Периодический опрос каналов — подстраховка если live-апдейты не работают"""
    await asyncio.sleep(30)  # Даём join'ам завершиться
    while True:
        try:
            channels = await _load_active_channels()
            for ch, cached_id in channels:
                if not cached_id:
                    continue
                if ch.startswith("+"):
                    continue
                try:
                    msgs = []
                    async for m in client.get_chat_history(ch, limit=1):
                        msgs.append(m)
                    if msgs:
                        m = msgs[0]
                        chat_id = m.chat.id
                        if chat_id not in _listening_ids:
                            continue
                        text = m.text or m.caption or ""
                        if not _is_casting(text):
                            continue
                        # Проверяем есть ли уже такой пост в БД по source_url
                        url = f"https://t.me/{ch}/{m.id}"
                        from database.session import async_session
                        from database.models import Casting
                        from sqlalchemy import select
                        async with async_session() as s:
                            exists = await s.scalar(select(Casting.id).where(Casting.source_url == url))
                            if not exists:
                                logger.info(f"POLL @{ch}: new casting id={m.id}")
                                asyncio.create_task(process_new_casting(text=text, source_url=url))
                except Exception as e:
                    logger.debug(f"POLL @{ch}: {e}")
            logger.info(f"Poll cycle complete ({len(channels)} channels)")
        except Exception as e:
            logger.warning(f"Poll error: {e}")
        await asyncio.sleep(180)  # Раз в 3 минуты


async def start_userbot():
    global app, _listening_ids, _bot_ready
    if not settings.API_ID or not settings.API_HASH:
        logger.warning("API_ID/HASH missing, skip."); return

    await _ensure_db_ready()

    delay = 5
    while True:
        try:
            channels = await _load_active_channels()
            if not channels:
                logger.warning("No active channels, retrying in 60s.")
                await asyncio.sleep(60)
                continue

            _listening_ids = set()
            for ch, cached_id in channels:
                # Always try to join — don't pre-cache, let join logic handle it
                pass
            logger.info(f"Starting userbot with {len(channels)} channels...")

            workdir = "/app" if os.path.isdir("/app") else "."
            app = Client("casting_userbot", api_id=settings.API_ID, api_hash=settings.API_HASH,
                         phone_number=settings.PHONE_NUMBER, workdir=workdir)
            await app.start()
            delay = 5

            # Регистрируем обработчик сразу — без фильтра по chat,
            # фильтрация по _listening_ids происходит внутри new_channel_message
            app.add_handler(MessageHandler(new_channel_message, filters.channel))
            logger.info("Handler registered. Starting background join...")

            # Запускаем вступление в каналы в фоне — не блокируя обработку событий
            asyncio.create_task(_join_and_resolve_bg(app, channels))

            # Запускаем polling-опрос каналов раз в 3 минуты
            asyncio.create_task(_poll_channels(app))

            try:
                while True:
                    await asyncio.sleep(3600)
            except asyncio.CancelledError:
                await app.stop()
                return

        except EOFError:
            logger.error("Session invalidated — re-auth required. Stopping.")
            return
        except Exception as e:
            logger.error(f"UserBot error: {e}. Reconnecting in {delay}s...")
            try:
                if app:
                    await app.stop()
            except Exception:
                pass
            app = None
            _listening_ids = set()
            _bot_ready = False
            await asyncio.sleep(delay)
            delay = min(delay * 2, 300)
