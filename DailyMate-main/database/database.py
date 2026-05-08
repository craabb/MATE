from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from core.config import settings
from .models import Base

engine = create_async_engine(settings.database_url, echo=False)
session_factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)

async def init_db():
    """Создание таблиц (вызывается только один раз при первом запуске)"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)