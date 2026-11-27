from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from app.api.v1 import workflow
from app.core.context import TenantContextMiddleware
from app.core.logging import setup_logging
from app.core.service_auth import ServiceAuthMiddleware
from app.db.session import init_db, close_db

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await init_db()
    yield
    await close_db()


app = FastAPI(
    title="Workflow Service",
    description="Workflow Orchestration Engine: Visual Editor, Execution Engine, Version Control",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 请求上下文（X-Tenant-Id / X-User-Id）
app.add_middleware(TenantContextMiddleware)

# 服务间签名校验（X-Service-Timestamp / X-Service-Signature）
app.add_middleware(ServiceAuthMiddleware)

metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# Routes
app.include_router(workflow.router, prefix="/api/v1")
app.include_router(workflow.version_router, prefix="/api/v1")
app.include_router(workflow.execution_router, prefix="/api/v1")
app.include_router(workflow.template_router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "workflow-service"}


@app.get("/ready")
async def readiness_check():
    """就绪探针：真 ping 一次数据库，连不上返回 503 而不是假装 ready。"""
    from fastapi.responses import JSONResponse
    from sqlalchemy import text

    from app.db.session import engine

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - 探针只需要知道失败原因
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "service": "workflow-service", "error": str(exc)[:200]},
        )
    return {"status": "ready", "service": "workflow-service"}