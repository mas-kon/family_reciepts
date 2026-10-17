from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _unicode_lower(value):
    return value.lower() if isinstance(value, str) else value


def _sqlite_pragmas(dbapi_conn, _record):
    # SQLite's built-in lower()/LIKE only fold ASCII; Cyrillic search needs a Unicode lower().
    dbapi_conn.create_function("lower", 1, _unicode_lower, deterministic=True)
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")
    cur.close()


def init_engine(url: str | None = None):
    global _engine, _sessionmaker
    url = url or get_settings().database_url
    _engine = create_async_engine(url)
    if url.startswith("sqlite"):
        event.listen(_engine.sync_engine, "connect", _sqlite_pragmas)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_engine():
    if _engine is None:
        init_engine()
    return _engine


def session_factory() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        init_engine()
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_factory()() as session:
        yield session


def icontains(column, text: str):
    """Case-insensitive substring match that works for Cyrillic on SQLite and PostgreSQL."""
    from sqlalchemy import func

    escaped = text.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return func.lower(column).like(f"%{escaped}%", escape="\\")
