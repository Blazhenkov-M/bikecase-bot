from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from typing import AsyncGenerator

from app.settings.config import settings


class Base(AsyncAttrs, DeclarativeBase):
    __abstract__ = True  # не создавать таблицу для Base


engine = create_async_engine(
    url=settings.database_url,
    echo=False,
    future=True,
    connect_args={"server_settings": {"timezone": "UTC"}},
    execution_options={"isolation_level": "READ COMMITTED"},
    pool_size=10,
    max_overflow=10)

async_session = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session
