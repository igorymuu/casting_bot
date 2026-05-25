from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from config import settings

engine = create_async_engine(settings.database_url, echo=True, connect_args={"check_same_thread": False})
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
