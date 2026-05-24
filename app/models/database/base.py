from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    echo=not settings.is_production,
    pool_pre_ping=True,
)

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


def make_worker_session() -> async_sessionmaker[AsyncSession]:
    """Create a NullPool-backed session factory safe for Celery worker event loops.

    Each call creates a fresh engine with NullPool so asyncpg connections are
    never cached across asyncio event loop boundaries.
    """
    _engine = create_async_engine(
        settings.database_url,
        poolclass=NullPool,
        echo=not settings.is_production,
    )
    return async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass
