import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    pass


def create_engine() -> AsyncEngine:
    return create_async_engine(
        settings.DATABASE_URL,
        echo=settings.DEBUG,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )


engine: AsyncEngine = create_engine()

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def session_context() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


logger = logging.getLogger(__name__)


def _run_alembic(command_name: str) -> None:
    """在独立线程执行 alembic（命令内部会 asyncio.run，不能在事件循环里直接调）。"""
    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    if command_name == "stamp":
        command.stamp(cfg, "head")
    else:
        command.upgrade(cfg, "head")


async def _stamp_legacy_db_if_needed() -> None:
    """create_all 建过表但没有 alembic_version 的旧库：先 stamp head，避免重复建表。

    注意：stamp **不校验结构差异**，只适用于本地/演示库；生产请先用 alembic check 比对。
    """

    def _needs_stamp(sync_conn) -> bool:
        names = inspect(sync_conn).get_table_names()
        return bool(names) and "alembic_version" not in names

    async with engine.connect() as conn:
        legacy = await conn.run_sync(_needs_stamp)
    if legacy:
        logger.warning("数据库已有表但没有 alembic_version，直接 stamp head（不校验结构差异）")
        await asyncio.to_thread(_run_alembic, "stamp")


async def init_db() -> None:
    # Import models to register them
    from app.models import (  # noqa: F401
        Document,
        DocumentChunk,
        KnowledgeBase,
    )
    if settings.DB_AUTO_MIGRATE:
        await _stamp_legacy_db_if_needed()
        await asyncio.to_thread(_run_alembic, "upgrade")
        logger.info("Database migrated to head via Alembic")
        return

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database schema ready via create_all — DB_AUTO_MIGRATE=false")


async def close_db() -> None:
    await engine.dispose()