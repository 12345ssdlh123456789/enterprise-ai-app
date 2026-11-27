import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


def create_engine() -> AsyncEngine:
    # SQLite hides no queues/threading limits; server pool options are skipped for local dev.
    kwargs = {"echo": settings.DEBUG, "pool_pre_ping": True}
    if not settings.DATABASE_URL.startswith("sqlite"):
        kwargs.update(pool_size=10, max_overflow=20)
    return create_async_engine(settings.DATABASE_URL, **kwargs)


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

    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))

    async def _table_names() -> list[str]:
        probe = create_async_engine(str(settings.DATABASE_URL), poolclass=NullPool)
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


async def init_db() -> None:
    """建表：Alembic 迁移（DB_AUTO_MIGRATE=true）或 create_all 兜底。"""
    from app.models import (  # noqa: F401
        Workflow,
        WorkflowVersion,
        WorkflowExecution,
        WorkflowExecutionLog,
        NodeTemplate,
    )

    if settings.DB_AUTO_MIGRATE:
        await asyncio.to_thread(_alembic_upgrade_sync)
        logger.info("Database migrated to head via Alembic")
    else:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database schema ready via create_all — DB_AUTO_MIGRATE=false")


async def close_db() -> None:
    await engine.dispose()