import datetime
import re

from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from bot.states import ProfileFSM
from database.models import User, ActorProfile

router = Router()

# ─── Константы ────────────────────────────────────────────────────────────────

CITIES = ["Москва", "Санкт-Петербург", "Все города"]

PROJECTS = [
    "Кино и сериалы",
    "Реклама",
    "Некоммерч./короткометражные фильмы",
    "Международные проекты",
    "Клипы",
    "Театр",
    "Озвучка/дубляж",
    "Другое",
]

OPTIONS = [
    "Исключить АМС (массовки, групповки)",
    "Только славянский типаж",
    "Не присылать кастинги от агентов",
]

# ─── Инлайн клавиатуры ────────────────────────────────────────────────────────

def gender_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(inline_keyboard=[[
        types.InlineKeyboardButton(text="Мужской", callback_data="gender_male"),
        types.InlineKeyboardButton(text="Женский", callback_data="gender_female"),
    ]])


def cities_keyboard(selected: list[str]) -> types.InlineKeyboardMarkup:
    rows = []
    for i, city in enumerate(CITIES):
        mark = "✅ " if city in selected else ""
        rows.append([types.InlineKeyboardButton(
            text=f"{mark}{city}",
            callback_data=f"city_{i}",
        )])
    rows.append([types.InlineKeyboardButton(text="✓ Готово", callback_data="city_done")])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def projects_keyboard(selected: list[str]) -> types.InlineKeyboardMarkup:
    rows = []
    for i, proj in enumerate(PROJECTS):
        mark = "✅ " if proj in selected else ""
        rows.append([types.InlineKeyboardButton(
            text=f"{mark}{proj}",
            callback_data=f"proj_{i}",
        )])
    rows.append([types.InlineKeyboardButton(text="✓ Готово", callback_data="proj_done")])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def options_keyboard(selected: list[str]) -> types.InlineKeyboardMarkup:
    rows = []
    for i, opt in enumerate(OPTIONS):
        mark = "✅ " if opt in selected else ""
        rows.append([types.InlineKeyboardButton(
            text=f"{mark}{opt}",
            callback_data=f"opt_{i}",
        )])
    rows.append([types.InlineKeyboardButton(text="✓ Готово", callback_data="opt_done")])
    return types.InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="Изменить профиль", callback_data="profile_restart")],
        [types.InlineKeyboardButton(text="Зарегистрироваться", callback_data="profile_save")],
    ])


def subscription_keyboard() -> types.InlineKeyboardMarkup:
    return types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="1 месяц — 690 ₽", callback_data="sub_1m")],
        [types.InlineKeyboardButton(text="3 месяца — 1 790 ₽", callback_data="sub_3m")],
        [types.InlineKeyboardButton(text="6 месяцев — 2 990 ₽", callback_data="sub_6m")],
        [types.InlineKeyboardButton(text="1 год — 4 990 ₽", callback_data="sub_12m")],
    ])


# ─── Формирование сводки ──────────────────────────────────────────────────────

def build_summary(d: dict, username: str) -> str:
    age = ""
    try:
        bd = datetime.date.fromisoformat(d["birth_date"])
        today = datetime.date.today()
        age = today.year - bd.year - ((today.month, today.day) < (bd.month, bd.day))
    except Exception:
        pass

    proj_map = {
        "Кино и сериалы": "Кино и сериалы",
        "Реклама": "Реклама",
        "Некоммерч./короткометражные фильмы": "Некоммерческие/короткометражные фильмы",
        "Международные проекты": "Международные проекты",
        "Клипы": "Клипы",
        "Театр": "Театр",
        "Озвучка/дубляж": "Озвучка/дубляж",
        "Другое": "Другое",
    }
    opt_map = {
        "Исключить АМС (массовки, групповки)": "Исключить АМС (массовки, групповки)",
        "Только славянский типаж": "Присылать кастинги только для славянского типажа",
        "Не присылать кастинги от агентов": "Не присылать кастинги от агентов",
    }

    selected_proj = d.get("project_types", [])
    selected_opts = d.get("extra_options", [])
    selected_cities = d.get("cities", [])

    proj_lines = "\n".join(
        f"{'✅' if p in selected_proj else '☐'} {label}"
        for p, label in proj_map.items()
    )
    city_lines = "\n".join(
        f"{'✅' if c in selected_cities else '☐'} {c}"
        for c in CITIES
    )
    opt_lines = "\n".join(
        f"{'✅' if o in selected_opts else '☐'} {label}"
        for o, label in opt_map.items()
    )

    return (
        f"Проверьте данные вашего профиля:\n\n"
        f"Имя: {d.get('full_name')}, {age} лет\n"
        f"Telegram: @{username or '—'}\n"
        f"Email: {d.get('email')}\n\n"
        f"Игр. возраст: {d.get('playing_age_min')}-{d.get('playing_age_max')}\n"
        f"Пол: {d.get('gender', '').lower()}\n"
        f"Гонорар: {d.get('min_fee')} руб.\n\n"
        f"<b>Категории:</b>\n{proj_lines}\n\n"
        f"<b>Город кастинга:</b>\n{city_lines}\n\n"
        f"<b>Доп. опции:</b>\n{opt_lines}"
    )


# ─── Шаг 0: Запуск FSM (callback от кнопки "Заполнить профиль") ──────────────

@router.callback_query(F.data == "fill_profile")
async def start_profile(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(ProfileFSM.full_name)
    await callback.answer()
    await callback.message.answer("Введите ваше Имя и Фамилию")


# ─── Шаг 1: Имя и фамилия ─────────────────────────────────────────────────────

@router.message(ProfileFSM.full_name)
async def step_full_name(message: types.Message, state: FSMContext):
    if len(message.text.strip()) < 2:
        await message.answer("Пожалуйста, введите имя и фамилию.")
        return
    await state.update_data(full_name=message.text.strip())
    await state.set_state(ProfileFSM.gender)
    await message.answer("Укажи свой пол", reply_markup=gender_keyboard())


# ─── Шаг 2: Пол ───────────────────────────────────────────────────────────────

@router.callback_query(ProfileFSM.gender, F.data.in_(["gender_male", "gender_female"]))
async def step_gender(callback: types.CallbackQuery, state: FSMContext):
    gender = "Мужской" if callback.data == "gender_male" else "Женский"
    await state.update_data(gender=gender)
    await state.set_state(ProfileFSM.birth_date)
    await callback.answer()
    await callback.message.edit_text(
        f"Пол: {gender} ✅\n\n"
        "Дата рождения\n\n"
        "Образец заполнения:\n"
        "28.06.1989",
    )


# ─── Шаг 3: Дата рождения ─────────────────────────────────────────────────────

@router.message(ProfileFSM.birth_date)
async def step_birth_date(message: types.Message, state: FSMContext):
    text = message.text.strip()
    if not re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", text):
        await message.answer("❌ Неверный формат. Введи дату в формате ДД.ММ.ГГГГ, например: 28.06.1989")
        return
    try:
        bd = datetime.datetime.strptime(text, "%d.%m.%Y").date()
    except ValueError:
        await message.answer("❌ Такой даты не существует. Попробуй ещё раз.")
        return
    if bd > datetime.date.today():
        await message.answer("❌ Дата рождения не может быть в будущем.")
        return

    await state.update_data(birth_date=bd.isoformat())
    await state.set_state(ProfileFSM.playing_age)
    await message.answer(
        "Игровой возраст (укажи диапазон, через дефис).\n\n"
        "Обычно это +5 лет и -5 лет от реального возраста. Например, если актёру 30, то его игровой возраст 25-35"
    )


# ─── Шаг 4: Игровой возраст ───────────────────────────────────────────────────

@router.message(ProfileFSM.playing_age)
async def step_playing_age(message: types.Message, state: FSMContext):
    text = message.text.strip()
    if not re.fullmatch(r"\d{1,3}-\d{1,3}", text):
        await message.answer("❌ Неверный формат. Введи диапазон через дефис, например: 20-30")
        return
    min_age, max_age = map(int, text.split("-"))
    if min_age >= max_age:
        await message.answer("❌ Минимальный возраст должен быть меньше максимального. Попробуй ещё раз.")
        return

    await state.update_data(playing_age_min=min_age, playing_age_max=max_age, cities=[])
    await state.set_state(ProfileFSM.cities)
    await message.answer(
        "Из каких городов тебе присылать кастинги:",
        reply_markup=cities_keyboard([]),
    )


# ─── Шаг 5: Города ────────────────────────────────────────────────────────────

@router.callback_query(ProfileFSM.cities, F.data.startswith("city_"))
async def step_cities(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected: list = data.get("cities", [])
    action = callback.data[len("city_"):]

    if action == "done":
        if not selected:
            await callback.answer("Выбери хотя бы один вариант.", show_alert=True)
            return
        await state.update_data(project_types=[])
        await state.set_state(ProfileFSM.project_types)
        await callback.answer()
        await callback.message.edit_text(
            "Кастинги в какие проекты тебя интересуют? (можно выбрать несколько)",
            reply_markup=projects_keyboard([]),
        )
        return

    try:
        city = CITIES[int(action)]
    except (ValueError, IndexError):
        await callback.answer()
        return

    if city in selected:
        selected.remove(city)
    else:
        selected.append(city)
    await state.update_data(cities=selected)
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=cities_keyboard(selected))


# ─── Шаг 6: Категории проектов ────────────────────────────────────────────────

@router.callback_query(ProfileFSM.project_types, F.data.startswith("proj_"))
async def step_projects(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected: list = data.get("project_types", [])
    action = callback.data[len("proj_"):]

    if action == "done":
        if not selected:
            await callback.answer("Выбери хотя бы одну категорию.", show_alert=True)
            return
        await state.set_state(ProfileFSM.min_fee)
        await callback.answer()
        await callback.message.edit_text(
            "Укажите <b>минимальный</b> гонорар за смену в рублях (цифрами без символов):\n\n"
            "<i>Образец заполнения:\n3000</i>",
            parse_mode="HTML",
        )
        return

    try:
        proj = PROJECTS[int(action)]
    except (ValueError, IndexError):
        await callback.answer()
        return

    if proj in selected:
        selected.remove(proj)
    else:
        selected.append(proj)
    await state.update_data(project_types=selected)
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=projects_keyboard(selected))


# ─── Шаг 7: Гонорар ───────────────────────────────────────────────────────────

@router.message(ProfileFSM.min_fee)
async def step_min_fee(message: types.Message, state: FSMContext):
    text = message.text.strip().replace(" ", "").replace(",", "")
    if not text.isdigit():
        await message.answer("❌ Пожалуйста, введи только цифры. Например: 5000")
        return
    await state.update_data(min_fee=int(text), extra_options=[])
    await state.set_state(ProfileFSM.extra_options)
    await message.answer(
        "Выберите дополнительные опции:",
        reply_markup=options_keyboard([]),
    )


# ─── Шаг 8: Доп. опции ────────────────────────────────────────────────────────

@router.callback_query(ProfileFSM.extra_options, F.data.startswith("opt_"))
async def step_extra_options(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected: list = data.get("extra_options", [])
    action = callback.data[len("opt_"):]

    if action == "done":
        await state.update_data(extra_options=selected)
        await state.set_state(ProfileFSM.email)
        await callback.answer()
        await callback.message.edit_text(
            "Укажите электронную почту, чтобы мы могли сохранить ваш профиль:",
        )
        return

    try:
        opt = OPTIONS[int(action)]
    except (ValueError, IndexError):
        await callback.answer()
        return

    if opt in selected:
        selected.remove(opt)
    else:
        selected.append(opt)
    await state.update_data(extra_options=selected)
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=options_keyboard(selected))


# ─── Шаг 9: Email ─────────────────────────────────────────────────────────────

@router.message(ProfileFSM.email)
async def step_email(message: types.Message, state: FSMContext):
    email = message.text.strip()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        await message.answer("❌ Неверный формат email. Попробуй ещё раз, например: name@gmail.com")
        return

    await state.update_data(email=email)
    data = await state.get_data()
    await state.set_state(ProfileFSM.confirm)

    summary = build_summary(data, message.from_user.username)
    await message.answer(
        summary,
        reply_markup=confirm_keyboard(),
        parse_mode="HTML",
    )


# ─── Шаг 10: Подтверждение ────────────────────────────────────────────────────

@router.callback_query(F.data == "profile_restart")
async def cb_profile_restart(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()
    await callback.message.answer(
        "Профиль сброшен. Нажми /start, чтобы начать заново.",
    )


@router.callback_query(F.data == "profile_save")
async def cb_profile_save(callback: types.CallbackQuery, state: FSMContext, session: AsyncSession):
    await callback.answer()
    data = await state.get_data()
    user_id = callback.from_user.id

    existing = await session.get(ActorProfile, user_id)
    if existing:
        await session.delete(existing)
        await session.flush()

    selected_proj = data.get("project_types", [])
    selected_opts = data.get("extra_options", [])

    profile = ActorProfile(
        user_id=user_id,
        full_name=data.get("full_name", ""),
        gender=data.get("gender", ""),
        birth_date=datetime.date.fromisoformat(data["birth_date"]),
        playing_age_min=data.get("playing_age_min", 0),
        playing_age_max=data.get("playing_age_max", 0),
        city=", ".join(data.get("cities", [])),

        proj_cinema="Кино и сериалы" in selected_proj,
        proj_ads="Реклама" in selected_proj,
        proj_nonprofit="Некоммерч./короткометражные фильмы" in selected_proj,
        proj_international="Международные проекты" in selected_proj,
        proj_clips="Клипы" in selected_proj,
        proj_theater="Театр" in selected_proj,
        proj_dubbing="Озвучка/дубляж" in selected_proj,
        proj_other="Другое" in selected_proj,

        min_fee=data.get("min_fee", 0),

        opt_exclude_ams="Исключить АМС (массовки, групповки)" in selected_opts,
        opt_slavic_appearance="Только славянский типаж" in selected_opts,
        opt_exclude_agents="Не присылать кастинги от агентов" in selected_opts,

        email=data.get("email"),
    )

    session.add(profile)
    await session.commit()
    await state.clear()

    from bot.handlers.base import main_keyboard
    await callback.message.answer(
        "Отлично! Твой профиль готов 🎉\n\n"
        "Сейчас покажу, как я работаю...",
        reply_markup=main_keyboard(),
    )
    await callback.message.answer(
        "🎥 <i>Здесь будет видео-кружочек с приветствием от создателей</i>",
        parse_mode="HTML",
    )
    await callback.message.answer(
        "Начнём подбирать тебе кастинги?😉\n\n"
        "Выбери подходящий вариант подписки:\n\n"
        "С подпиской ты первым узнаёшь о новых кастингах и успеваешь подать заявку раньше остальных.",
        reply_markup=subscription_keyboard(),
    )


# sub_* callbacks handled by cabinet.router (payment flow)
