# alembic/env.py

import sys
import os
from logging.config import fileConfig
from pathlib import Path

# 添加项目根目录到 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# 导入模型
from app.models import Base
from app.core.config import settings

# this is the Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 设置目标 metadata
target_metadata = Base.metadata


def get_database_url() -> str:
    """Alembic 使用的 URL：**保持 async 驱动**。

    服务依赖里只有 aiosqlite / asyncpg，没有 psycopg（同步驱动）。
    以前这里把 `+asyncpg` 去掉，SQLAlchemy 2 会去找 psycopg → `ModuleNotFoundError: psycopg`，
    导致 `alembic upgrade head` 在 Postgres 上从来跑不起来。
    在线迁移走 `async_engine_from_config`，离线模式只需要方言渲染 SQL，两者都能用 async URL。
    """
    return str(settings.ASYNC_DATABASE_URL)


def render_item(type_, obj, autogen_context):
    """自定义类型（app.db.types.GUID / JSONType / InetType）没有 import 时会生成坏迁移。

    autogenerate 只会输出 `app.db.types.GUID()` 这样的字符串，不会带 import，
    导致 `alembic upgrade` 直接 NameError。这里把 import 塞进模板的 `${imports}`。
    """
    if type_ == "type" and getattr(obj.__class__, "__module__", "") == "app.db.types":
        autogen_context.imports.add("import app.db.types")
        return f"app.db.types.{obj.__class__.__name__}()"
    return False


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_schemas=True,
        render_item=render_item,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_schemas=True,
        render_item=render_item,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine."""
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = get_database_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    import asyncio
    asyncio.run(run_async_migrations())