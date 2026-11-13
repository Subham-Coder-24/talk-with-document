import logging
from collections.abc import AsyncIterator

from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

log = logging.getLogger(__name__)

engine = create_async_engine(settings.database_url, pool_pre_ping=True, pool_size=10)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    metadata = MetaData(schema=settings.db_schema)


class DbState:
    """Runtime facts discovered at startup."""

    pgvector: bool = False


db_state = DbState()


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    """Create schema/tables (idempotent) and detect optional pgvector support."""
    from app import models  # noqa: F401  (register mappers)

    schema = settings.db_schema
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))

    # pgvector is optional: if the extension is installed on the server we use it
    # for in-database similarity search, otherwise we fall back to NumPy.
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        db_state.pgvector = True
    except Exception as exc:  # extension files not installed / no privilege
        db_state.pgvector = False
        log.warning("pgvector not available (%s); using NumPy vector search", type(exc).__name__)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    log.info("Database ready (schema=%s, pgvector=%s)", schema, db_state.pgvector)
