"""Database engine and session factory management for RedCell_OS."""

import os

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.domain.engagement import Base


def get_database_url() -> str:
    """Resolve database URL from settings or data directory."""
    data_dir = os.path.abspath(settings.data_dir)
    os.makedirs(data_dir, exist_ok=True)
    db_path = os.path.join(data_dir, "redcell_global.db")
    return f"sqlite+aiosqlite:///{db_path}"


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            get_database_url(),
            echo=False,
            future=True,
            poolclass=pool.NullPool,  # NullPool ensures async connections work across distinct event loops
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    engine = get_engine()
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    """Create all relational tables if they do not exist."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    """Cleanly dispose the database engine on shutdown."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
