# API Gateway - Database Setup

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Generator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

logger = logging.getLogger(__name__)


def _ensure_sqlite_dir(url: str) -> None:
    """SQLite 文件目录不存在时自动创建，否则启动会直接报 unable to open database file。"""
    if not url.startswith("sqlite"):
        return
    raw = url.split("///", 1)[-1]
    if not raw or raw == ":memory:":
        return
    path = Path(raw)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_dir(settings.SYNC_DATABASE_URL)

_engine_kwargs: dict = {"pool_pre_ping": True, "echo": settings.DATABASE_ECHO}
if not settings.IS_SQLITE:
    _engine_kwargs.update(
        pool_size=settings.DATABASE_POOL_SIZE,
        max_overflow=settings.DATABASE_MAX_OVERFLOW,
        pool_timeout=settings.DATABASE_POOL_TIMEOUT,
    )


# ============================================
# 同步引擎 (用于 Alembic 迁移、Celery 任务)
# ============================================

sync_engine = create_engine(settings.SYNC_DATABASE_URL, **_engine_kwargs)

SyncSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)


def get_sync_db() -> Generator:
    """同步数据库会话 (用于非异步场景)"""
    db = SyncSessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================
# 异步引擎 (FastAPI 主流程)
# ============================================

async_engine = create_async_engine(settings.ASYNC_DATABASE_URL, **_engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """异步数据库会话依赖注入"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ============================================
# 基础模型类
# ============================================

class Base(DeclarativeBase):
    """所有模型的基类"""
    pass


# ============================================
# 数据库初始化
# ============================================

def _alembic_upgrade_sync() -> None:
    """在独立线程里跑 `alembic upgrade head`（Alembic 内部会 asyncio.run）。

    旧库处理：`create_all` 建过表、但没有 `alembic_version` 的库，直接 upgrade 会因为
    “table already exists” 挂掉。先 stamp head 再 upgrade——注意这 **不校验结构差异**，
    只适用于本地/演示库；生产请用 `alembic check` 先比对。
    """
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect

    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))

    engine = create_engine(settings.SYNC_DATABASE_URL, pool_pre_ping=True)
    try:
        inspector = inspect(engine)
        table_names = inspector.get_table_names()
        if table_names and "alembic_version" not in table_names:
            logger.warning(
                "数据库已有 %d 张表但没有 alembic_version，直接 stamp head（不校验结构差异）：%s",
                len(table_names),
                settings.SYNC_DATABASE_URL.rsplit("/", 1)[-1],
            )
            command.stamp(cfg, "head")
    finally:
        engine.dispose()

    command.upgrade(cfg, "head")


async def init_db() -> None:
    """初始化数据库（迁移建表 + 演示数据）"""
    # 导入所有模型以确保注册
    from app.models import (  # noqa: F401
        APIKey,
        AuditLog,
        Conversation,
        CostRecord,
        Document,
        DocumentChunk,
        KnowledgeBase,
        Message,
        Model,
        Notification,
        RefreshToken,
        SystemConfig,
        Tenant,
        TokenBudget,
        User,
        Workflow,
        WorkflowExecution,
    )

    if settings.DB_AUTO_MIGRATE:
        # 放到线程里：Alembic 的命令会自己 asyncio.run，不能在已运行的事件循环里直接调
        await asyncio.to_thread(_alembic_upgrade_sync)
        logger.info(
            "Database migrated to head via Alembic (%s)",
            "sqlite" if settings.IS_SQLITE else "postgresql",
        )
    else:
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info(
            "Database schema ready via create_all (%s) — DB_AUTO_MIGRATE=false",
            "sqlite" if settings.IS_SQLITE else "postgresql",
        )

    if settings.BOOTSTRAP_DEMO_DATA:
        from app.db.bootstrap import bootstrap_demo_data

        async with AsyncSessionLocal() as session:
            await bootstrap_demo_data(session)
            await session.commit()


async def close_db() -> None:
    """关闭数据库连接"""
    await async_engine.dispose()
    sync_engine.dispose()


@asynccontextmanager
async def lifespan_db():
    """应用生命周期管理"""
    await init_db()
    yield
    await close_db()
