from aiogram.fsm.state import State, StatesGroup


class ProfileFSM(StatesGroup):
    full_name = State()
    gender = State()
    birth_date = State()
    playing_age = State()
    cities = State()
    project_types = State()
    min_fee = State()
    extra_options = State()
    email = State()
    confirm = State()
