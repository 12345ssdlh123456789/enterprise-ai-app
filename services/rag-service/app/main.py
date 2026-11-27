from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

from app.api.v1 import rag
from app.core.context import TenantContextMiddleware
from app.db.session import init_db, close_db
from app.core.logging import setup_logging
from app.core.service_auth import ServiceAuthMiddleware

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await init_db()
    yield
    await close_db()


app = FastAPI(
    title="RAG Service",
    description="Enterprise RAG Pipeline: Document Processing, Hybrid Retrieval, Rerank",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# CORS
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

# Prometheus metrics
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# Routes
app.include_router(rag.router, prefix="/api/v1")
app.include_router(rag.doc_router, prefix="/api/v1")
app.include_router(rag.retrieval_router, prefix="/api/v1")
app.include_router(rag.embedding_router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "rag-service"}


@app.get("/ready")
async def readiness_check():
    """就绪探针：真 ping 一次数据库（pgvector 依赖），连不上返回 503。"""
    from fastapi.responses import JSONResponse
    from sqlalchemy import text

    from app.db.session import engine

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - 探针只需要知道失败原因
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "service": "rag-service", "error": str(exc)[:200]},
        )
    return {"status": "ready", "service": "rag-service"}