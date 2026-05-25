import logging
import datetime
from aiogram import Router, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func

from config import settings
from parser.service import process_new_casting
from database.session import async_session
from database.models import User, ActorProfile

router = Router()
logger = logging.getLogger(__name__)

# Фильтр на админа
router.message.filter(F.from_user.id.in_(settings.ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(settings.ADMIN_IDS))

class AdminStates(StatesGroup):
    waiting_for_user_id = State()

def get_admin_keyboard():
    kb = [
        [types.KeyboardButton(text="📊 Статистика")],
        [types.KeyboardButton(text="👥 Управление юзерами")]
    ]
    return types.ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

@router.message(Command("admin"))
async def cmd_admin(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("🛠 Панель администратора:", reply_markup=get_admin_keyboard())

@router.message(Command("parse"))
async def cmd_parse(message: types.Message):
    await message.answer(
        "Пришли мне текст кастинга в следующем сообщении, и я спаршу его, "
        "добавлю в базу и разошлю подходящим актерам."
    )

@router.message(F.text == "📊 Статистика")
async def show_statistics(message: types.Message):
    async with async_session() as session:
        # Всего юзеров
        total_users_q = await session.execute(select(func.count(User.telegram_id)))
        total_users = total_users_q.scalar()
        
        # Всего заполненных профилей
        total_profiles_q = await session.execute(select(func.count(ActorProfile.user_id)))
        total_profiles = total_profiles_q.scalar()
        
        # Активные подписки (дата окончания > сейчас)
        active_subs_q = await session.execute(
            select(func.count(ActorProfile.user_id))
            .where(ActorProfile.subscription_end_date > datetime.datetime.now())
        )
        active_subs = active_subs_q.scalar()
        
        text = (
            "<b>📊 Статистика бота:</b>\n\n"
            f"Всего юзеров: <b>{total_users}</b>\n"
            f"Заполненных профилей: <b>{total_profiles}</b>\n"
            f"Активных подписок: <b>{active_subs}</b>\n"
        )
        await message.answer(text)

@router.message(F.text == "👥 Управление юзерами")
async def manage_users(message: types.Message, state: FSMContext):
    await message.answer(
        "Введите <b>ID пользователя</b> (или перешлите его сообщение сюда), "
        "чтобы открыть меню управления."
    )
    await state.set_state(AdminStates.waiting_for_user_id)

@router.message(StateFilter(AdminStates.waiting_for_user_id), (F.text & ~F.text.startswith('/')) | F.forward_from)
async def process_user_id(message: types.Message, state: FSMContext):
    user_id = None
    if message.forward_from:
        user_id = message.forward_from.id
    elif message.text and message.text.isdigit():
        user_id = int(message.text)
        
    if not user_id:
        await message.answer("❌ Не удалось определить ID. Введите числовой ID или перешлите сообщение пользователя.")
        return

    await state.clear()
    await show_user_management_panel(message, user_id)

async def show_user_management_panel(message: types.Message, target_user_id: int, is_edit=False):
    async with async_session() as session:
        user = await session.get(User, target_user_id)
        if not user:
            text = f"❌ Пользователь с ID <code>{target_user_id}</code> не найден в базе."
            if is_edit:
                await message.edit_text(text)
            else:
                await message.answer(text)
            return
            
        profile = await session.get(ActorProfile, target_user_id)
        
        sub_status = "❌ Нет подписки"
        sub_end = "---"
        if profile and profile.subscription_end_date:
            if profile.subscription_end_date > datetime.datetime.now():
                sub_status = "✅ Активна"
            else:
                sub_status = "⚠️ Истекла"
            sub_end = profile.subscription_end_date.strftime('%d.%m.%Y %H:%M')
            
        username = f"@{user.username}" if user.username else "Нет"
        full_name = profile.full_name if profile else "Профиль не заполнен"
        
        text = (
            f"👤 <b>Пользователь:</b> <a href='tg://user?id={target_user_id}'>{full_name}</a>\n"
            f"🆔 <b>ID:</b> <code>{target_user_id}</code>\n"
            f"📧 <b>Username:</b> {username}\n"
            f"📅 <b>Дата регистрации:</b> {user.created_at.strftime('%d.%m.%Y')}\n\n"
            f"💳 <b>Статус подписки:</b> {sub_status}\n"
            f"⏳ <b>До:</b> {sub_end}"
        )
        
        kb = [
            [
                types.InlineKeyboardButton(text="➕ 1 день", callback_data=f"admin_addsub_{target_user_id}_1"),
                types.InlineKeyboardButton(text="➕ 30 дней", callback_data=f"admin_addsub_{target_user_id}_30")
            ],
            [
                types.InlineKeyboardButton(text="➕ 1 год", callback_data=f"admin_addsub_{target_user_id}_365"),
                types.InlineKeyboardButton(text="❌ Забрать доступ", callback_data=f"admin_rmsub_{target_user_id}")
            ]
        ]
        markup = types.InlineKeyboardMarkup(inline_keyboard=kb)
        
        if is_edit:
            await message.edit_text(text, reply_markup=markup)
        else:
            await message.answer(text, reply_markup=markup)

@router.callback_query(F.data.startswith("admin_addsub_"))
async def cb_add_sub(callback: types.CallbackQuery):
    _, _, user_id_str, days_str = callback.data.split("_")
    target_user_id = int(user_id_str)
    days = int(days_str)
    
    async with async_session() as session:
        profile = await session.get(ActorProfile, target_user_id)
        if not profile:
            await callback.answer("❌ У пользователя не заполнен профиль!", show_alert=True)
            return
            
        current_end = profile.subscription_end_date or datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        
        if current_end < datetime.datetime.now():
            current_end = datetime.datetime.now()
            
        new_end = current_end + datetime.timedelta(days=days)
        profile.subscription_end_date = new_end
        
        # Обновляем поле has_subscription в User
        user = await session.get(User, target_user_id)
        if user:
            user.has_subscription = True
            
        await session.commit()
        
    await callback.answer(f"✅ Доступ выдан на {days} дн.", show_alert=True)
    
    # Пытаемся оповестить юзера
    try:
        await callback.bot.send_message(
            target_user_id,
            f"🎉 <b>Отличные новости!</b>\nАдминистратор выдал вам доступ на {days} дней.\n"
            f"Подписка активна до: {new_end.strftime('%d.%m.%Y %H:%M')}"
        )
    except Exception as e:
        logger.warning(f"Не удалось оповестить {target_user_id}: {e}")
        
    # Обновляем панель
    await show_user_management_panel(callback.message, target_user_id, is_edit=True)

@router.callback_query(F.data.startswith("admin_rmsub_"))
async def cb_rm_sub(callback: types.CallbackQuery):
    _, _, user_id_str = callback.data.split("_")
    target_user_id = int(user_id_str)
    
    async with async_session() as session:
        profile = await session.get(ActorProfile, target_user_id)
        if profile:
            profile.subscription_end_date = datetime.datetime.now() - datetime.timedelta(days=1)
            
        user = await session.get(User, target_user_id)
        if user:
            user.has_subscription = False
            
        await session.commit()
        
    await callback.answer("❌ Доступ успешно отозван.", show_alert=True)
    
    # Пытаемся оповестить юзера
    try:
        await callback.bot.send_message(
            target_user_id,
            "⚠️ <b>Внимание!</b>\nАдминистратор приостановил вашу подписку."
        )
    except Exception as e:
        logger.warning(f"Не удалось оповестить {target_user_id}: {e}")

    # Обновляем панель
    await show_user_management_panel(callback.message, target_user_id, is_edit=True)


@router.message(F.text & ~F.text.startswith('/'), StateFilter(None))
async def handle_casting_text(message: types.Message):
    # Пропускаем команды клавиатуры админа
    if message.text in ["📊 Статистика", "👥 Управление юзерами"]:
        return
        
    if len(message.text) < 20:
        return
        
    await message.answer("Передаю текст в LLM для парсинга. Подождите...")
    
    try:
        await process_new_casting(text=message.text)
        await message.answer("✅ Кастинг успешно обработан и сохранен! Рассылка запущена.")
    except Exception as e:
        logger.error(f"Error handling admin casting text: {e}")
        await message.answer(f"❌ Ошибка при обработке: {e}")
