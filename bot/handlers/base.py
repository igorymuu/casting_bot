from aiogram import Router, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database.models import User, Casting, Favorite
from sqlalchemy.exc import IntegrityError

router = Router()

def main_keyboard():
    return types.ReplyKeyboardMarkup(
        keyboard=[[
            types.KeyboardButton(text="📁 Личный кабинет"),
            types.KeyboardButton(text="📩 Поддержка"),
        ], [
            types.KeyboardButton(text="🏠 Главное меню"),
        ]],
        resize_keyboard=True,
        is_persistent=True,
    )



def role_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="🎭 Актёр", callback_data="role_actor"),
            types.InlineKeyboardButton(text="🎬 Кастинг-директор", callback_data="role_cd"),
        ],
        [types.InlineKeyboardButton(text="🎥 Режиссёр", callback_data="role_director")],
    ])


def fill_profile_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="✏️ Заполнить профиль", callback_data="fill_profile")]
    ])


@router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext, session: AsyncSession):
    await state.clear()  # сбрасываем любое состояние, в т.ч. AdminStates.waiting_for_user_id

    # Парсим referral
    referral_id = None
    if message.text and "ref_" in message.text:
        try:
            ref_str = message.text.split("ref_")[-1].split()[0]
            referral_id = int(ref_str)
            if referral_id == message.from_user.id:
                referral_id = None  # нельзя пригласить себя
        except (ValueError, IndexError):
            referral_id = None

    # Если у пользователя уже есть профиль — показываем кабинет
    from database.models import ActorProfile
    result = await session.execute(select(ActorProfile).where(ActorProfile.user_id == message.from_user.id))
    profile = result.scalar_one_or_none()
    if profile:
        from bot.handlers.cabinet import lk_inline_keyboard
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

    # Сохраняем referral (если есть) — в User
    if referral_id:
        result = await session.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = result.scalar_one_or_none()
        if user and not user.referred_by:
            user.referred_by = referral_id
            await session.commit()

    await message.answer(
        "Привет! Я — твой проводник в мир кино и рекламы. Буду твоим информатором по кастингам😎\n\n"
        "🎯 Отслеживаю кастинги в самых крупных tg-каналах и других источниках в реальном времени (800+ кастингов ежедневно).\n\n"
        "Присылаю только подходящие — по полу, возрасту, типу проекта.\n\n"
        "📍 Москва, Санкт-Петербург\n"
        "+ международные проекты🌍, где рассматривают русских актёров со знанием англ. языка.\n\n"
        "🤚 Бот охотится в основном за кастингами для взрослых актёров. Детские роли тоже встречаются, но не так часто.\n"
        "——\n\n"
        "🎬 <b>Заполним профиль и начнём подбирать для тебя кастинги?</b>\n\n"
        "<i>Регистрируя профиль, вы даёте согласие на обработку персональных данных и принимаете условия публичной оферты</i>",
        reply_markup=fill_profile_keyboard(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )



@router.callback_query(F.data.in_(["role_cd", "role_director"]))
async def cb_role_other(callback: types.CallbackQuery, session: AsyncSession):
    role_map = {
        "role_cd": "Кастинг-директор",
        "role_director": "Режиссёр",
    }
    role = role_map[callback.data]

    result = await session.execute(select(User).where(User.telegram_id == callback.from_user.id))
    user = result.scalar_one_or_none()
    if not user:
        user = User(telegram_id=callback.from_user.id, username=callback.from_user.username)
        session.add(user)
    user.role = role
    await session.commit()
    await callback.answer()

    await callback.message.edit_text(
        f"Раздел для роли «{role}» находится в разработке.\nСледите за обновлениями!",
    )


from database.models import Casting

@router.callback_query(F.data.startswith("cast_more_"))
async def cb_cast_more(callback: types.CallbackQuery, session: AsyncSession):
    casting_id = int(callback.data.split("_")[-1])
    casting = await session.get(Casting, casting_id)
    if not casting:
        await callback.answer("Кастинг не найден")
        return

    full_text = f"🎯 <b>Найден новый подходящий кастинг!</b>\n\n"
    full_text += f"<b>{casting.title}</b>\n\n"
    full_text += f"{casting.description}\n\n"
    if casting.source_url:
        full_text += f"🔗 <a href='{casting.source_url}'>Ссылка на источник</a>"

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [
            types.InlineKeyboardButton(text="В избранное ❤️", callback_data=f"cast_fav_{casting.id}"),
            types.InlineKeyboardButton(text="Не нравится ❌", callback_data=f"cast_hide_{casting.id}")
        ]
    ])

    await callback.message.edit_text(
        text=full_text,
        reply_markup=kb,
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await callback.answer()

@router.callback_query(F.data.startswith("cast_hide_"))
async def cb_cast_hide(callback: types.CallbackQuery):
    await callback.message.delete()
    await callback.answer("Кастинг скрыт ❌")

@router.callback_query(F.data.startswith("cast_fav_"))
async def cb_cast_fav(callback: types.CallbackQuery, session: AsyncSession):
    casting_id = int(callback.data.replace("cast_fav_", ""))
    fav = Favorite(user_id=callback.from_user.id, casting_id=casting_id)
    session.add(fav)
    try:
        await session.commit()
        await callback.answer("Добавлено в избранное ❤️", show_alert=True)
    except IntegrityError:
        await session.rollback()
        await callback.answer("Уже в избранном ❤️", show_alert=True)
