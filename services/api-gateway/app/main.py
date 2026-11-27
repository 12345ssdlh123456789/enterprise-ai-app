# API Gateway - Main Application

import logging
import sys
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from app.core.response import UTF8JSONResponse
from fastapi.openapi.utils import get_openapi
from prometheus_client import make_asgi_app
from sqlalchemy import text

from app.core.config import settings
from app.core.middleware import (
    RequestLoggingMiddleware,
    MetricsMiddleware,
    SecurityHeadersMiddleware,
    ExceptionHandlerMiddleware,
    ServiceAuthMiddleware,
    create_cors_middleware,
)
from app.db.session import init_db, close_db, AsyncSessionLocal
from app.schemas import HealthCheckResponse, ServiceHealthCheck


# ============================================
# 配置日志
# ============================================

def setup_logging():
    """配置结构化日志"""
    import structlog

    # 标准库日志配置
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.LOG_LEVEL.upper()),
    )

    # structlog 配置
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if settings.LOG_FORMAT == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


setup_logging()

logger = logging.getLogger(__name__)


# ============================================
# Redis 客户端 (全局)
# ============================================

redis_client = None


async def get_redis():
    """获取 Redis 客户端"""
    global redis_client
    if redis_client is None:
        import redis.asyncio as redis
        redis_client = redis.from_url(
            str(settings.REDIS_URL),
            encoding="utf-8",
            decode_responses=True,
            max_connections=settings.DATABASE_POOL_SIZE,
            protocol=2,
        )
    return redis_client


async def close_redis():
    """关闭 Redis 连接"""
    global redis_client
    if redis_client:
        await redis_client.close()
        redis_client = None


# ============================================
# 生命周期管理
# ============================================

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期"""
    # 启动
    logger.info(
        "Starting API Gateway version=%s environment=%s",
        settings.APP_VERSION,
        settings.ENVIRONMENT,
    )

    # 初始化数据库
    await init_db()
    logger.info("Database initialized")

    # 初始化 Redis
    await get_redis()
    logger.info("Redis connected")

    yield

    # 关闭
    logger.info("Shutting down API Gateway")
    await close_db()
    await close_redis()
    logger.info("Shutdown complete")


# ============================================
# 创建 FastAPI 应用
# ============================================

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="智汇 AI 工作台 - API 网关",
    docs_url=None,  # 自定义 docs
    redoc_url=None,
    openapi_url=f"{settings.API_PREFIX}/openapi.json",
    lifespan=lifespan,
    default_response_class=UTF8JSONResponse,
)

# 添加中间件 (顺序很重要！)
# 1. 异常处理 (最外层)
app.add_middleware(ExceptionHandlerMiddleware)

# 2. 安全头
app.add_middleware(SecurityHeadersMiddleware)

# 3. CORS
create_cors_middleware(app)

# 4. 服务认证
app.add_middleware(ServiceAuthMiddleware)

# 5. 限流 (需要 Redis)
# app.add_middleware(RateLimitMiddleware, redis_client=redis_client)  # 启动后添加

# 6. 指标收集
if settings.ENABLE_METRICS:
    app.add_middleware(MetricsMiddleware)

# 7. 请求日志 (最内层，最接近路由)
app.add_middleware(RequestLoggingMiddleware)

# 挂载 Prometheus metrics endpoint
if settings.ENABLE_METRICS:
    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)


# ============================================
# 自定义 OpenAPI
# ============================================

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="智汇 AI 工作台 - API 网关\n\n## 认证\n\n除健康检查和认证接口外，所有 API 端点均需要 JWT Bearer 令牌身份认证。\n\n```\nAuthorization: Bearer <access_token>\n```\n\n## 限流\n\nAPI 请求受限流。查看响应头：\n- `X-RateLimit-Limit`: 请求窗口限制\n- `X-RateLimit-Remaining`: 剩余请求数\n- `X-RateLimit-Reset`: 限制重置的 Unix 时间戳\n\n## 错误响应\n\n所有错误遵循标准格式：\n```json\n{\n  \"success\": false,\n  \"error\": {\n    \"code\": \"错误码\",\n    \"message\": \"人类可读的消息\",\n    \"details\": {}\n  }\n}\n```",
        routes=app.routes,
    )

    # 添加安全方案
    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        },
        "APIKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "Authorization",
            "description": "Service-to-service API Key (format: Bearer eak_xxx)",
        },
    }

    # 全局安全要求
    openapi_schema["security"] = [{"BearerAuth": []}]

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi


# ============================================
# 自定义 Docs
# ============================================

@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=f"{settings.APP_NAME} - Swagger UI",
        oauth2_redirect_url=None,
        swagger_js_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js",
        swagger_css_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css",
    )


@app.get("/redoc", include_in_schema=False)
async def redoc_html():
    return get_redoc_html(
        openapi_url=app.openapi_url,
        title=f"{settings.APP_NAME} - ReDoc",
        redoc_js_url="https://cdn.jsdelivr.net/npm/redoc@next/bundles/redoc.standalone.js",
    )


# ============================================
# 健康检查
# ============================================

@app.get("/health", tags=["Health"])
async def health_check():
    """健康检查端点"""
    from datetime import datetime
    import time

    checks = {}

    # 数据库检查
    try:
        started = time.perf_counter()
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        checks["database"] = ServiceHealthCheck(
            status="healthy",
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )
    except Exception as e:
        checks["database"] = ServiceHealthCheck(status="unhealthy", details={"error": str(e)})

    # Redis 检查
    try:
        redis = await get_redis()
        await redis.ping()
        checks["redis"] = ServiceHealthCheck(status="healthy", latency_ms=1.0)
    except Exception as e:
        checks["redis"] = ServiceHealthCheck(status="unhealthy", details={"error": str(e)})

    # 确定整体状态
    all_healthy = all(c.status == "healthy" for c in checks.values())
    any_unhealthy = any(c.status == "unhealthy" for c in checks.values())

    if any_unhealthy:
        overall_status = "unhealthy"
    elif all_healthy:
        overall_status = "healthy"
    else:
        overall_status = "degraded"

    return HealthCheckResponse(
        status=overall_status,
        version=settings.APP_VERSION,
        timestamp=datetime.now(),
        checks=checks,
    )


@app.get("/health/live", tags=["Health"])
async def liveness_check():
    """存活检查 (Kubernetes liveness probe)"""
    return {"status": "alive"}


@app.get("/health/ready", tags=["Health"])
async def readiness_check():
    """就绪检查 (Kubernetes readiness probe)

    数据库是硬依赖；Redis 仅用于限流/缓存，本地没启动时不影响主流程，
    所以降级为 degraded 而不是直接 503。
    """
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
    except Exception:
        return UTF8JSONResponse(
            status_code=503,
            content={"status": "not ready", "database": "unavailable"},
        )

    redis_status = "ok"
    try:
        redis = await get_redis()
        await redis.ping()
    except Exception:
        redis_status = "unavailable"

    return UTF8JSONResponse(
        status_code=200,
        content={
            "status": "ready" if redis_status == "ok" else "degraded",
            "database": "ok",
            "redis": redis_status,
        },
    )


# ============================================
# 根路径重定向
# ============================================

@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/docs")


# ============================================
# 导入并注册路由
# ============================================

# 认证路由
from app.api.v1 import auth as auth_router
app.include_router(auth_router.router, prefix=settings.API_PREFIX, tags=["Authentication"])

# 用户路由
from app.api.v1 import users as users_router
app.include_router(users_router.router, prefix=settings.API_PREFIX, tags=["Users"])

# 租户路由
from app.api.v1 import tenants as tenants_router
app.include_router(tenants_router.router, prefix=settings.API_PREFIX, tags=["Tenants"])

# 知识库路由
from app.api.v1 import knowledge_bases as kb_router
app.include_router(kb_router.router, prefix=settings.API_PREFIX, tags=["Knowledge Bases"])

# 文档转发（试点）：必须注册在网关自带 documents 路由之前，否则永远匹配不到。
# GATEWAY_PROXY_DOCUMENTS=false（默认）时网关仍是单体，由下面自己的路由处理。
if settings.GATEWAY_PROXY_DOCUMENTS:
    from app.api.v1 import proxy as proxy_router
    app.include_router(proxy_router.router, prefix=settings.API_PREFIX, tags=["Gateway Proxy"])
    logger.info(
        "Gateway proxy enabled: /documents, /upload, /download -> %s",
        settings.DOCUMENT_SERVICE_URL,
    )

# 文档路由
from app.api.v1 import documents as docs_router
app.include_router(docs_router.router, prefix=settings.API_PREFIX, tags=["Documents"])

# 对话/聊天路由
from app.api.v1 import conversations as conv_router
app.include_router(conv_router.router, prefix=settings.API_PREFIX, tags=["Conversations"])

# 工作流转发（试点）：同样必须注册在自带 workflows 路由之前
if settings.GATEWAY_PROXY_WORKFLOWS:
    from app.api.v1 import proxy_workflows as proxy_wf_router
    app.include_router(proxy_wf_router.router, prefix=settings.API_PREFIX, tags=["Gateway Proxy"])
    logger.info(
        "Gateway proxy enabled: /workflows -> %s", settings.WORKFLOW_SERVICE_URL
    )

# 工作流路由
from app.api.v1 import workflows as wf_router
app.include_router(wf_router.router, prefix=settings.API_PREFIX, tags=["Workflows"])

# 检索路由
from app.api.v1 import retrieval as retrieval_router
app.include_router(retrieval_router.router, prefix=settings.API_PREFIX, tags=["Retrieval"])

# 模型路由
from app.api.v1 import models as models_router
app.include_router(models_router.router, prefix=settings.API_PREFIX, tags=["Models"])

# 审计日志路由
from app.api.v1 import audit_logs as audit_router
app.include_router(audit_router.router, prefix=settings.API_PREFIX, tags=["Audit Logs"])

# 通知转发：必须注册在自带 notifications 路由之前（否则永远匹配不到）。
# GATEWAY_PROXY_NOTIFICATIONS=false（默认）时由下面自己的路由处理。
if settings.GATEWAY_PROXY_NOTIFICATIONS:
    from app.api.v1 import proxy_notifications as proxy_notif_router
    app.include_router(
        proxy_notif_router.router, prefix=settings.API_PREFIX, tags=["Gateway Proxy"]
    )
    logger.info(
        "Gateway proxy enabled: /notifications -> %s", settings.NOTIFICATION_SERVICE_URL
    )

# 通知路由
from app.api.v1 import notifications as notif_router
app.include_router(notif_router.router, prefix=settings.API_PREFIX, tags=["Notifications"])

# 成本追踪路由
from app.api.v1 import costs as costs_router
app.include_router(costs_router.router, prefix=settings.API_PREFIX, tags=["Costs"])

# 系统配置路由
from app.api.v1 import system_configs as config_router
app.include_router(config_router.router, prefix=settings.API_PREFIX, tags=["System Configs"])

# API Key 路由
from app.api.v1 import api_keys as apikey_router
app.include_router(apikey_router.router, prefix=settings.API_PREFIX, tags=["API Keys"])

# 内部服务路由 (internal router 自带 /internal 前缀)
from app.api.internal import router as internal_router
app.include_router(internal_router, prefix="/api/v1", tags=["Internal"])


# ============================================
# 入口点
# ============================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_config=None,  # 使用 structlog
    )