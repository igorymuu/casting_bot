import datetime
from typing import Optional
from sqlalchemy import String, Date, Integer, DateTime, ForeignKey, Boolean, Text, JSON, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'

    telegram_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    has_subscription: Mapped[bool] = mapped_column(Boolean, default=False)
    referred_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=None)  # кто пригласил
    discount_used: Mapped[bool] = mapped_column(Boolean, default=False)  # использовал ли скидку 25%
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.datetime.utcnow()
    )


class ActorProfile(Base):
    __tablename__ = 'actor_profiles'

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey('users.telegram_id'), primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255))
    gender: Mapped[str] = mapped_column(String(50))
    birth_date: Mapped[Optional[datetime.date]] = mapped_column(Date, nullable=True)
    playing_age_min: Mapped[int] = mapped_column(Integer, default=0)
    playing_age_max: Mapped[int] = mapped_column(Integer, default=0)
    city: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Категории проектов
    proj_cinema: Mapped[bool] = mapped_column(Boolean, default=False)
    proj_ads: Mapped[bool] = mapped_column(Boolean, default=False)
    proj_nonprofit: Mapped[bool] = mapped_column(Boolean, default=False)
    proj_international: Mapped[bool] = mapped_column(Boolean, default=False)
    proj_clips: Mapped[bool] = mapped_column(Boolean, default=False)
    proj_theater: Mapped[bool] = mapped_column(Boolean, default=False)
    proj_dubbing: Mapped[bool] = mapped_column(Boolean, default=False)
    proj_other: Mapped[bool] = mapped_column(Boolean, default=False)

    min_fee: Mapped[int] = mapped_column(Integer, default=0)

    # Доп. опции
    opt_exclude_ams: Mapped[bool] = mapped_column(Boolean, default=False)
    opt_slavic_appearance: Mapped[bool] = mapped_column(Boolean, default=False)
    opt_exclude_agents: Mapped[bool] = mapped_column(Boolean, default=False)

    # Для интеграции ЮKassa
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    subscription_end_date: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)


class Casting(Base):
    __tablename__ = 'castings'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True) # Оригинальный текст кастинга
    criteria: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True) # Структурированные данные после LLM
    source_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    published_at: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime, nullable=True)


class ParsedChannel(Base):
    """Telegram-каналы для мониторинга кастингов."""
    __tablename__ = 'parsed_channels'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(255), unique=True)  # без @, e.g. "castings"
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)  # отображаемое название
    chat_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # кэш Telegram chat_id
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    added_at: Mapped[datetime.datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.datetime.utcnow()
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # заметки администратора


class Favorite(Base):
    """Избранные кастинги пользователя."""
    __tablename__ = 'favorites'
    __table_args__ = (UniqueConstraint('user_id', 'casting_id'),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey('users.telegram_id'))
    casting_id: Mapped[int] = mapped_column(Integer, ForeignKey('castings.id'))
    added_at: Mapped[datetime.datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.datetime.utcnow()
    )


class Match(Base):
    __tablename__ = 'matches'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[int] = mapped_column(Integer, ForeignKey('actor_profiles.user_id'))
    casting_id: Mapped[int] = mapped_column(Integer, ForeignKey('castings.id'))
    status: Mapped[str] = mapped_column(String(50), default='pending')
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.datetime.utcnow()
    )
