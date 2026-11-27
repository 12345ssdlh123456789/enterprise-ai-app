"""Notification Service main application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.context import TenantContextMiddleware
from app.core.logging import setup_logging
from app.core.service_auth import ServiceAuthMiddleware
from app.db.session import init_engine, init_db, close_db
from app.api.v1 import notifications

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    init_engine(
        settings.database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
    )
    try:
        await init_db()
        logger.info("database initialized")
    except Exception as e:
        logger.warning(f"database init failed (will retry on first request): {e}")
    logger.info("notification-service started")
    yield
    await close_db()
    logger.info("notification-service shutdown")


app = FastAPI(
    title="Notification Service",
    description="通知服务（邮件、Webhook、系统通知）",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 租户 / 用户上下文（X-Tenant-Id / X-User-Id，网关转发时注入；非法 UUID 直接 400）
app.add_middleware(TenantContextMiddleware)

# 服务间签名校验（X-Service-Timestamp / X-Service-Signature）
app.add_middleware(ServiceAuthMiddleware)

app.include_router(notifications.router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "notification-service", "version": "1.0.0"}


@app.get("/ready")
async def ready():
    """就绪探针：真 ping 一次数据库，连不上返回 503。"""
    from sqlalchemy import text

    from app.db.session import engine

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - 探针只需要知道失败原因
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "service": "notification-service", "error": str(exc)[:200]},
        )
    return {"status": "ready", "service": "notification-service"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
