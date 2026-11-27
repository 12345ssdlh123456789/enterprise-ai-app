"""Notification Service database session management."""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


engine = None
async_session = None


def init_engine(database_url: str, pool_size: int = 10, max_overflow: int = 20):
    global engine, async_session
    kwargs = {"echo": False}
    if not database_url.startswith("sqlite"):
        kwargs["pool_size"] = pool_size
        kwargs["max_overflow"] = max_overflow
    engine = create_async_engine(database_url, **kwargs)
    async_session = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def get_session() -> AsyncSession:
    async with async_session() as session:
        yield session


def _alembic_upgrade_sync() -> None:
    """在独立线程里跑 `alembic upgrade head`（Alembic 内部会自己 asyncio.run）。

    旧库处理：以前用 `create_all` 建过表、却没有 `alembic_version` 的库，直接 upgrade 会
    因为 “table already exists” 挂掉。先 stamp head 再 upgrade——这 **不校验结构差异**，
    只适用于本地/演示库；生产请先 `alembic check` 比对。
    """
    import asyncio
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from app.core.config import settings

    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))

    async def _table_names() -> list[str]:
        probe = create_async_engine(settings.database_url, poolclass=NullPool)
        try:
            async with probe.connect() as conn:
                return await conn.run_sync(lambda c: inspect(c).get_table_names())
        finally:
            await probe.dispose()

    tables = asyncio.run(_table_names())
    if tables and "alembic_version" not in tables:
        logger.warning(
            "数据库已有 %d 张表但没有 alembic_version，直接 stamp head（不校验结构差异）",
            len(tables),
        )
        command.stamp(cfg, "head")
    command.upgrade(cfg, "head")


async def init_db():
    """建表：Alembic 迁移（DB_AUTO_MIGRATE=true）或 create_all 兜底。"""
    from app.core.config import settings

    from app.models.notification import Notification  # noqa: F401

    if settings.db_auto_migrate:
        await asyncio.to_thread(_alembic_upgrade_sync)
        logger.info("Database migrated to head via Alembic")
        return

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database schema ready via create_all — DB_AUTO_MIGRATE=false")


async def close_db():
    if engine:
        await engine.dispose()
