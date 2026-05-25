from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database.models import User, ActorProfile, Casting, Favorite
import datetime
import logging
import aiohttp

router = Router()

PACKAGES = {
    "sub_1m":  {"label": "1 месяц",    "price": 690,  "days": 30},
    "sub_3m":  {"label": "3 месяца",   "price": 1790, "days": 90},
    "sub_6m":  {"label": "6 месяцев",  "price": 2990, "days": 180},
    "sub_12m": {"label": "1 год",      "price": 4990, "days": 365},
}

class PayFSM(StatesGroup):
    waiting_email = State()

PROJECT_LABELS = {
    "proj_cinema": "Кино и сериалы", "proj_ads": "Реклама",
    "proj_nonprofit": "Некоммерч./короткометражные", "proj_international": "Международные",
    "proj_clips": "Клипы", "proj_theater": "Театр",
    "proj_dubbing": "Озвучка/дубляж", "proj_other": "Другое",
}
OPTION_LABELS = {
    "opt_exclude_ams": "Исключить АМС",
    "opt_slavic_appearance": "Только славянский типаж",
    "opt_exclude_agents": "Не присылать от агентов",
}

def format_profile(profile):
    age = ""
    if profile.birth_date:
        today = datetime.date.today()
        age = today.year - profile.birth_date.year - (
            (today.month, today.day) < (profile.birth_date.month, profile.birth_date.day))
    projects = [label for key, label in PROJECT_LABELS.items() if getattr(profile, key, False)]
    options  = [label for key, label in OPTION_LABELS.items() if getattr(profile, key, False)]
    sub_status = "❌ Нет подписки"
    if profile.subscription_end_date:
        if profile.subscription_end_date > datetime.datetime.utcnow():
            sub_status = f"✅ Активна до {profile.subscription_end_date.strftime('%d.%m.%Y')}"
        else:
            sub_status = "⚠️ Истекла"
    return (
        f"<b>👤 Мой профиль</b>\n\n"
        f"Имя: {profile.full_name}\n"
        f"Пол: {profile.gender}\n"
        f"Дата рождения: {profile.birth_date.strftime('%d.%m.%Y') if profile.birth_date else '—'} ({age} лет)\n"
        f"Игровой возраст: {profile.playing_age_min}–{profile.playing_age_max}\n"
        f"Город: {profile.city or '—'}\n"
        f"Проекты: {', '.join(projects) or '—'}\n"
        f"Гонорар: от {profile.min_fee:,} руб./смену\n"
        f"Email: {profile.email or '—'}\n\n"
        f"Подписка: {sub_status}"
    )

# ─── Главное меню (reply keyboard) ───────────────────────────

from aiogram.fsm.context import FSMContext
from bot.handlers.base import main_keyboard, role_keyboard

logger = logging.getLogger(__name__)

@router.message(F.text.contains("Главное меню"))
async def menu_home(message: types.Message, state: FSMContext, session: AsyncSession):
    logger.info(f"Главное меню pressed by {message.from_user.id}")
    await state.clear()
    from database.models import ActorProfile
    result = await session.execute(select(ActorProfile).where(ActorProfile.user_id == message.from_user.id))
    profile = result.scalar_one_or_none()
    if profile:
        from bot.handlers.base import main_keyboard
        await message.answer(
            "Привет! Я — твой проводник в мир кино и рекламы. Буду твоим информатором по кастингам😎\n\n"
            "🎯 Отслеживаю кастинги в самых крупных tg-каналах и других источниках в реальном времени (800+ кастингов ежедневно).\n\n"
            "Присылаю только подходящие — по полу, возрасту, типу проекта.\n\n"
            "📍 Москва, Санкт-Петербург\n"
            "+ международные проекты🌍, где рассматривают русских актёров со знанием англ. языка.\n\n"
            "🤚 Бот охотится в основном за кастингами для взрослых актёров. Детские роли тоже встречаются, но не так часто.\n"
            "——\n\n"
            "🎬 Заполним профиль и начнём подбирать для тебя кастинги?\n\n"
            "Регистрируя профиль, вы даёте согласие на обработку персональных данных и принимаете условия публичной оферты",
            reply_markup=main_keyboard(),
        )
        return

    from database.models import User
    from bot.handlers.base import main_keyboard, role_keyboard
    await message.answer(
        "👋 Добро пожаловать! Выберите вашу роль:",
        reply_markup=role_keyboard(),
    )

def lk_inline_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="👤 Мой профиль",       callback_data="lk_profile")],
        [types.InlineKeyboardButton(text="❤️ Избранное",          callback_data="lk_favorites")],
        [types.InlineKeyboardButton(text="💳 Моя подписка",       callback_data="lk_subscription")],
        [types.InlineKeyboardButton(text="👥 Пригласить друга",   callback_data="lk_invite")],
    ])

@router.message(F.text.contains("Личный кабинет"))
async def menu_lk(message: types.Message, session: AsyncSession):
    result = await session.execute(select(ActorProfile).where(ActorProfile.user_id == message.from_user.id))
    profile = result.scalar_one_or_none()
    if not profile:
        await message.answer("У вас ещё нет профиля. Нажмите /start чтобы зарегистрироваться.", reply_markup=main_keyboard())
        return
    await message.answer(
        "📂 <b>Личный кабинет</b>\nВыберите раздел:",
        reply_markup=lk_inline_keyboard(),
        parse_mode="HTML",
    )
    # reply keyboard stays persistent via is_persistent in main_keyboard

@router.message(F.text.lower().contains("поддержка"))
async def menu_support(message: types.Message):
    user_id = message.from_user.id
    # Регистрируем источник в боте поддержки через HTTP
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(
                "http://host.docker.internal:8765/register_source",
                json={"user_id": user_id, "source": "casting"},
                timeout=aiohttp.ClientTimeout(total=2),
            )
    except Exception as e:
        logging.getLogger(__name__).warning(f"Failed to register source for {user_id}: {e}")

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="📨 Написать в поддержку", url="https://t.me/sup_neuro_bot?start=casting")],
    ])
    await message.answer(
        "📨 <b>Поддержка</b>\n\n"
        "Если у вас возникли вопросы или проблемы — нажмите кнопку ниже, "
        "чтобы написать в поддержку:\n",
        parse_mode="HTML",
        reply_markup=kb,
    )

# ─── LK inline callbacks ──────────────────────────────────────

@router.callback_query(F.data == "lk_profile")
async def cb_lk_profile(callback: types.CallbackQuery, session: AsyncSession):
    await callback.answer()
    result = await session.execute(select(ActorProfile).where(ActorProfile.user_id == callback.from_user.id))
    profile = result.scalar_one_or_none()
    if not profile:
        await callback.message.answer("Профиль не заполнен. Нажмите /start")
        return
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="✏️ Редактировать профиль", callback_data="edit_profile")],
        [types.InlineKeyboardButton(text="← Назад", callback_data="lk_back")],
    ])
    await callback.message.edit_text(format_profile(profile), reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data == "lk_subscription")
async def cb_lk_subscription(callback: types.CallbackQuery, session: AsyncSession):
    await callback.answer()

    # Проверяем статус подписки
    result = await session.execute(select(ActorProfile).where(ActorProfile.user_id == callback.from_user.id))
    profile = result.scalar_one_or_none()

    now = datetime.datetime.utcnow()
    sub_active = profile and profile.subscription_end_date and profile.subscription_end_date > now

    if sub_active:
        until = profile.subscription_end_date.strftime("%d.%m.%Y")
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="🔁 Продлить подписку", callback_data="sub_renew")],
            [types.InlineKeyboardButton(text="← Назад", callback_data="lk_back")],
        ])
        await callback.message.edit_text(
            f"💳 <b>Подписка</b>\n\n"
            f"✅ <b>Подписка активна</b>\n"
            f"📅 Действует до: <b>{until}</b>\n\n"
            f"Ты первым узнаёшь о новых кастингах и успеваешь подать заявку раньше других.",
            reply_markup=kb, parse_mode="HTML",
        )
    else:
        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text="1 месяц — 690 ₽",    callback_data="sub_1m")],
            [types.InlineKeyboardButton(text="3 месяца — 1 790 ₽",  callback_data="sub_3m")],
            [types.InlineKeyboardButton(text="6 месяцев — 2 990 ₽", callback_data="sub_6m")],
            [types.InlineKeyboardButton(text="1 год — 4 990 ₽",     callback_data="sub_12m")],
            [types.InlineKeyboardButton(text="← Назад", callback_data="lk_back")],
        ])
        await callback.message.edit_text(
            "💳 <b>Подписка</b>\n\nВыберите тариф:\n\n"
            "С подпиской ты первым узнаёшь о новых кастингах и успеваешь подать заявку раньше остальных.",
            reply_markup=kb, parse_mode="HTML",
        )

@router.callback_query(F.data == "lk_favorites")
async def cb_lk_favorites(callback: types.CallbackQuery, session: AsyncSession):
    await callback.answer()
    result = await session.execute(
        select(Casting)
        .join(Favorite, Favorite.casting_id == Casting.id)
        .where(Favorite.user_id == callback.from_user.id)
        .order_by(Favorite.added_at.desc())
        .limit(20)
    )
    castings = result.scalars().all()

    kb_rows = []
    if castings:
        for c in castings:
            label = (c.title[:40] + "…") if len(c.title) > 40 else c.title
            kb_rows.append([types.InlineKeyboardButton(
                text=f"❤️ {label}",
                callback_data=f"fav_view_{c.id}"
            )])
    kb_rows.append([types.InlineKeyboardButton(text="← Назад", callback_data="lk_back")])
    kb = types.InlineKeyboardMarkup(inline_keyboard=kb_rows)

    if castings:
        text = f"❤️ <b>Избранное</b>\n\nСохранённых кастингов: {len(castings)}"
    else:
        text = "❤️ <b>Избранное</b>\n\nВы ещё не сохранили ни одного кастинга.\n\nНажимайте «В избранное ❤️» когда видите подходящий кастинг."

    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("fav_view_"))
async def cb_fav_view(callback: types.CallbackQuery, session: AsyncSession):
    casting_id = int(callback.data.replace("fav_view_", ""))
    casting = await session.get(Casting, casting_id)
    if not casting:
        await callback.answer("Кастинг не найден", show_alert=True)
        return
    await callback.answer()
    text = f"<b>{casting.title}</b>\n\n{casting.description or ''}"
    if casting.source_url:
        text += f"\n\n🔗 <a href='{casting.source_url}'>Источник</a>"
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🗑 Убрать из избранного", callback_data=f"fav_del_{casting_id}")],
        [types.InlineKeyboardButton(text="← Назад к избранному", callback_data="lk_favorites")],
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)


@router.callback_query(F.data.startswith("fav_del_"))
async def cb_fav_del(callback: types.CallbackQuery, session: AsyncSession):
    casting_id = int(callback.data.replace("fav_del_", ""))
    result = await session.execute(
        select(Favorite).where(Favorite.user_id == callback.from_user.id, Favorite.casting_id == casting_id)
    )
    fav = result.scalar_one_or_none()
    if fav:
        await session.delete(fav)
        await session.commit()
    await callback.answer("Удалено из избранного")
    # Обновить список
    await cb_lk_favorites(callback, session)

@router.callback_query(F.data == "lk_invite")
async def cb_lk_invite(callback: types.CallbackQuery):
    await callback.answer()
    bot_link = f"https://t.me/casting_new_bot?start=ref_{callback.from_user.id}"
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(
            text="🔗 Поделиться ссылкой",
            url=f"https://t.me/share/url?url={bot_link}&text=Присоединяйся+к+боту+кастингов!+По+твоей+ссылке+скидка+25%25+на+подписку!"
        )],
        [types.InlineKeyboardButton(text="← Назад", callback_data="lk_back")],
    ])
    await callback.message.edit_text(
        f"👥 <b>Пригласить друга</b>\n\n"
        f"Поделитесь ссылкой с друзьями-актёрами:\n"
        f"<code>{bot_link}</code>\n\n"
        f"🎉 <b>Партнёрская программа:</b>\n"
        f"• Друг получает <b>скидку 25%</b> на подписку\n"
        f"• Ты тоже можешь получить скидку от друга\n\n"
        f"Чем больше актёров — тем шире сеть кастингов!",
        reply_markup=kb, parse_mode="HTML",
    )

@router.callback_query(F.data == "lk_back")
async def cb_lk_back(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "📂 <b>Личный кабинет</b>\nВыберите раздел:",
        reply_markup=lk_inline_keyboard(),
        parse_mode="HTML",
    )

# ─── /lk command ──────────────────────────────────────────────

@router.message(Command("lk"))
async def cmd_cabinet(message: types.Message, session: AsyncSession):
    import logging; logging.getLogger(__name__).info(f"cmd_cabinet (/lk) by {message.from_user.id}")
    result = await session.execute(select(ActorProfile).where(ActorProfile.user_id == message.from_user.id))
    profile = result.scalar_one_or_none()
    if not profile:
        await message.answer("У вас ещё нет профиля. Нажмите /start.")
        return
    await message.answer(
        "📂 <b>Личный кабинет</b>\nВыберите раздел:",
        reply_markup=lk_inline_keyboard(),
        parse_mode="HTML",
    )

@router.callback_query(F.data == "edit_profile")
async def cb_edit_profile(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer("Для редактирования профиля используйте /start.")

@router.callback_query(F.data == "buy_subscription")
async def cb_buy_subscription(callback: types.CallbackQuery):
    await callback.answer()
    await cb_lk_subscription(callback)

@router.callback_query(F.data == "sub_renew")
async def cb_sub_renew(callback: types.CallbackQuery):
    """Продление подписки — показываем тарифы."""
    await callback.answer()
    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="1 месяц — 690 ₽",    callback_data="sub_1m")],
        [types.InlineKeyboardButton(text="3 месяца — 1 790 ₽",  callback_data="sub_3m")],
        [types.InlineKeyboardButton(text="6 месяцев — 2 990 ₽", callback_data="sub_6m")],
        [types.InlineKeyboardButton(text="1 год — 4 990 ₽",     callback_data="sub_12m")],
        [types.InlineKeyboardButton(text="← Назад", callback_data="lk_subscription")],
    ])
    await callback.message.edit_text(
        "💳 <b>Продление подписки</b>\n\nВыберите новый тариф:\n\n"
        "Продление продлит текущую подписку сразу после её окончания.",
        reply_markup=kb, parse_mode="HTML",
    )

# ─── Payment flow ─────────────────────────────────────────────

@router.callback_query(F.data.in_(["sub_1m", "sub_3m", "sub_6m", "sub_12m"]))
async def cb_select_package(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    await callback.answer()
    pkg = callback.data
    result = await session.execute(select(ActorProfile).where(ActorProfile.user_id == callback.from_user.id))
    profile = result.scalar_one_or_none()
    await state.update_data(package=pkg)
    if profile and profile.email:
        await _create_payment_and_send(callback.message, callback.from_user.id, pkg, profile.email, state, session)
    else:
        await state.set_state(PayFSM.waiting_email)
        await callback.message.answer(
            f"Тариф: <b>{PACKAGES[pkg]['label']}</b> — {PACKAGES[pkg]['price']} руб.\n\nВведите email для получения чека:",
            parse_mode="HTML"
        )

@router.message(PayFSM.waiting_email)
async def process_email(message: types.Message, state: FSMContext, session: AsyncSession):
    email = message.text.strip()
    if "@" not in email or "." not in email:
        await message.answer("Некорректный email. Попробуйте снова:")
        return
    data = await state.get_data()
    pkg = data.get("package", "sub_1m")
    result = await session.execute(select(ActorProfile).where(ActorProfile.user_id == message.from_user.id))
    profile = result.scalar_one_or_none()
    if profile:
        profile.email = email
        await session.commit()
    await _create_payment_and_send(message, message.from_user.id, pkg, email, state, session)

async def _create_payment_and_send(message, user_id: int, pkg: str, email: str, state, session):
    from config import settings
    import uuid
    from yookassa import Configuration, Payment as YKPayment
    Configuration.account_id = settings.YOOKASSA_SHOP_ID
    Configuration.secret_key = settings.YOOKASSA_SECRET_KEY
    info = PACKAGES[pkg]

    # Проверяем — есть ли у пользователя реферал и не использована ли уже скидка
    user = await session.get(User, user_id)
    has_discount = user and user.referred_by is not None and not user.discount_used

    original_price = info["price"]
    if has_discount:
        discounted_price = int(original_price * 0.75)  # 25% скидка
    else:
        discounted_price = original_price

    try:
        payment = YKPayment.create({
            "amount": {"value": f"{discounted_price}.00", "currency": "RUB"},
            "confirmation": {"type": "redirect", "return_url": "https://t.me/casting_new_bot"},
            "description": f"Подписка {info['label']} — Casting Bot{' (со скидкой)' if has_discount else ''}",
            "receipt": {
                "customer": {"email": email},
                "items": [{
                    "description": f"Подписка на кастинги {info['label']}",
                    "quantity": "1",
                    "amount": {"value": f"{discounted_price}.00", "currency": "RUB"},
                    "vat_code": 1, "payment_mode": "full_payment", "payment_subject": "service"
                }]
            },
            "metadata": {"user_id": str(user_id), "package": pkg, "days": str(info["days"])},
            "capture": True,
        }, str(uuid.uuid4()))
        pay_url = payment.confirmation.confirmation_url

        discount_text = f"\n🎉 <b>Скидка 25% по партнёрской программе!</b>\nЦена со скидкой: <b>{discounted_price} ₽</b> (было {original_price} ₽)" if has_discount else ""

        kb = types.InlineKeyboardMarkup(inline_keyboard=[
            [types.InlineKeyboardButton(text=f"Оплатить {discounted_price} ₽", url=pay_url)],
            [types.InlineKeyboardButton(text="Я оплатил — проверить", callback_data=f"check_pay_{payment.id}")],
        ])
        await message.answer(
            f"<b>Платёж создан!</b>\n\n"
            f"Тариф: {info['label']}\n"
            f"Сумма: {discounted_price} ₽\n"
            f"Чек: {email}\n"
            f"{discount_text}\n\n"
            "Нажмите кнопку для оплаты, затем вернитесь и нажмите <b>Я оплатил</b>.",
            reply_markup=kb, parse_mode="HTML"
        )
    except Exception as e:
        await message.answer(f"Ошибка создания платежа: {e}")
    await state.clear()

@router.callback_query(F.data.startswith("check_pay_"))
async def cb_check_payment(callback: types.CallbackQuery, session: AsyncSession):
    await callback.answer("Проверяю...")
    payment_id = callback.data.replace("check_pay_", "")
    from config import settings
    from yookassa import Configuration, Payment as YKPayment
    Configuration.account_id = settings.YOOKASSA_SHOP_ID
    Configuration.secret_key = settings.YOOKASSA_SECRET_KEY
    try:
        payment = YKPayment.find_one(payment_id)
        if payment.status == "succeeded":
            user_id = int(payment.metadata.get("user_id", callback.from_user.id))
            days    = int(payment.metadata.get("days", 30))
            result  = await session.execute(select(ActorProfile).where(ActorProfile.user_id == user_id))
            profile = result.scalar_one_or_none()
            user    = await session.get(User, user_id)
            if profile:
                now = datetime.datetime.utcnow()
                cur = profile.subscription_end_date or now
                if cur < now:
                    cur = now
                profile.subscription_end_date = cur + datetime.timedelta(days=days)
                if user:
                    user.has_subscription = True
                    # Если была скидка по рефералу — помечаем использованной (один раз)
                    if user.referred_by and not user.discount_used:
                        user.discount_used = True
                await session.commit()
                until = profile.subscription_end_date.strftime("%d.%m.%Y")
                await callback.message.edit_text(
                    f"✅ Оплата прошла успешно!\n\n<b>Подписка активна до {until}</b>\n"
                    "Теперь вы будете получать подходящие кастинги!",
                    parse_mode="HTML"
                )
        elif payment.status == "pending":
            await callback.message.answer("Оплата ещё не завершена. Попробуйте чуть позже.")
        elif payment.status == "canceled":
            await callback.message.answer("Платёж отменён. Попробуйте снова — /lk")
        else:
            await callback.message.answer(f"Статус: {payment.status}. Обратитесь к администратору.")
    except Exception as e:
        await callback.message.answer(f"Ошибка проверки платежа: {e}")
