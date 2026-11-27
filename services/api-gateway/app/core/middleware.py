# API Gateway - Middleware

import time
import uuid
import logging
from typing import Callable, Optional
from contextvars import ContextVar

from fastapi import Request, Response, HTTPException
from app.core.response import UTF8JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from prometheus_client import Counter, Histogram, Gauge

from app.core.config import settings
from app.core.security import verify_service_token

# ============================================
# 请求 ID 上下文
# ============================================

request_id_var: ContextVar[str] = ContextVar("request_id", default="")
tenant_id_var: ContextVar[str] = ContextVar("tenant_id", default="")
user_id_var: ContextVar[str] = ContextVar("user_id", default="")


def get_request_id() -> str:
    return request_id_var.get()


def get_tenant_id() -> str:
    return tenant_id_var.get()


def get_user_id() -> str:
    return user_id_var.get()


# ============================================
# Prometheus 指标
# ============================================

http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

http_requests_in_progress = Gauge(
    "http_requests_in_progress",
    "HTTP requests in progress",
    ["method", "endpoint"],
)

rate_limit_exceeded_total = Counter(
    "rate_limit_exceeded_total",
    "Total rate limit exceeded",
    ["identifier", "type"],
)


# ============================================
# 请求日志中间件
# ============================================

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """请求日志中间件"""

    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.logger = logging.getLogger("api.request")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 生成请求 ID
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request_id_var.set(request_id)

        # 记录开始时间
        start_time = time.time()

        # 获取客户端 IP
        client_ip = request.client.host if request.client else "unknown"
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()

        # 记录请求信息
        self.logger.info(
            "Request started",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "query": str(request.query_params),
                "client_ip": client_ip,
                "user_agent": request.headers.get("User-Agent", ""),
            },
        )

        # 处理请求
        try:
            response = await call_next(request)
        except Exception as e:
            # 记录异常
            duration = time.time() - start_time
            self.logger.error(
                "Request failed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round(duration * 1000, 2),
                    "error": str(e),
                },
                exc_info=True,
            )
            raise

        # 记录响应
        duration = time.time() - start_time
        self.logger.info(
            "Request completed",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration * 1000, 2),
            },
        )

        # 添加响应头
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{duration:.3f}s"

        return response


# ============================================
# 指标收集中间件
# ============================================

class MetricsMiddleware(BaseHTTPMiddleware):
    """Prometheus 指标收集中间件"""

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not settings.ENABLE_METRICS:
            return await call_next(request)

        # 标准化路径 (将路径参数替换为占位符)
        path = self._normalize_path(request.url.path)
        method = request.method

        # 增加进行中计数
        http_requests_in_progress.labels(method=method, endpoint=path).inc()

        start_time = time.time()
        status_code = 500

        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except HTTPException as e:
            status_code = e.status_code
            raise
        except Exception:
            status_code = 500
            raise
        finally:
            # 记录指标
            duration = time.time() - start_time
            http_request_duration_seconds.labels(method=method, endpoint=path).observe(duration)
            http_requests_total.labels(method=method, endpoint=path, status=status_code).inc()
            http_requests_in_progress.labels(method=method, endpoint=path).dec()

    def _normalize_path(self, path: str) -> str:
        """标准化路径，将 UUID 等动态部分替换为占位符"""
        import re
        # 替换 UUID
        path = re.sub(r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "/{id}", path)
        # 替换数字 ID
        path = re.sub(r"/\d+(?=/|$)", "/{id}", path)
        return path


# ============================================
# 限流中间件
# ============================================

class RateLimitMiddleware(BaseHTTPMiddleware):
    """限流中间件 (基于 Redis 滑动窗口)"""

    def __init__(self, app: ASGIApp, redis_client):
        super().__init__(app)
        self.redis = redis_client

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)

        # 排除健康检查和静态资源
        if request.url.path in ["/health", "/metrics", "/docs", "/redoc", "/openapi.json"]:
            return await call_next(request)

        # 获取标识符 (用户 ID 或 IP)
        identifier = self._get_identifier(request)
        if not identifier:
            return await call_next(request)

        # 检查限流
        allowed, retry_after = await self._check_rate_limit(identifier, request.url.path)

        if not allowed:
            rate_limit_exceeded_total.labels(identifier=identifier, type="request").inc()
            return UTF8JSONResponse(
                status_code=429,
                content={
                    "success": False,
                    "error": {
                        "code": "RATE_LIMIT_EXCEEDED",
                        "message": "Too many requests. Please try again later.",
                        "details": {"retry_after": retry_after},
                    },
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(settings.RATE_LIMIT_MAX_REQUESTS),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time()) + retry_after),
                },
            )

        response = await call_next(request)

        # 添加限流头
        remaining = await self._get_remaining(identifier)
        response.headers["X-RateLimit-Limit"] = str(settings.RATE_LIMIT_MAX_REQUESTS)
        response.headers["X-RateLimit-Remaining"] = str(max(0, remaining))
        response.headers["X-RateLimit-Reset"] = str(int(time.time()) + settings.RATE_LIMIT_WINDOW_SECONDS)

        return response

    def _get_identifier(self, request: Request) -> Optional[str]:
        """获取限流标识符"""
        # 优先使用用户 ID
        user_id = get_user_id()
        if user_id:
            return f"user:{user_id}"

        # 其次使用租户 ID
        tenant_id = get_tenant_id()
        if tenant_id:
            return f"tenant:{tenant_id}"

        # 最后使用 IP
        client_ip = request.client.host if request.client else "unknown"
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()
        return f"ip:{client_ip}"

    async def _check_rate_limit(self, identifier: str, path: str) -> tuple[bool, int]:
        """检查限流 (滑动窗口算法)"""
        now = time.time()
        window_start = now - settings.RATE_LIMIT_WINDOW_SECONDS
        key = f"ratelimit:{identifier}"

        async with self.redis.pipeline() as pipe:
            # 移除过期记录
            pipe.zremrangebyscore(key, 0, window_start)
            # 获取当前计数
            pipe.zcard(key)
            # 添加当前请求
            pipe.zadd(key, {str(now): now})
            # 设置过期时间
            pipe.expire(key, settings.RATE_LIMIT_WINDOW_SECONDS + 1)
            results = await pipe.execute()

        current_count = results[1]
        allowed = current_count < settings.RATE_LIMIT_MAX_REQUESTS
        retry_after = settings.RATE_LIMIT_WINDOW_SECONDS if not allowed else 0

        return allowed, retry_after

    async def _get_remaining(self, identifier: str) -> int:
        """获取剩余配额"""
        now = time.time()
        window_start = now - settings.RATE_LIMIT_WINDOW_SECONDS
        key = f"ratelimit:{identifier}"

        count = await self.redis.zcount(key, window_start, "+inf")
        return settings.RATE_LIMIT_MAX_REQUESTS - count


# ============================================
# CORS 中间件配置
# ============================================

def create_cors_middleware(app: ASGIApp):
    """创建 CORS 中间件"""
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Response-Time", "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
        max_age=3600,
    )


# ============================================
# 安全头中间件
# ============================================

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """安全头中间件"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        # 安全头
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

        # CSP (根据需要调整)
        if settings.ENVIRONMENT == "production":
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
                "style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: https:; "
                "font-src 'self' data:; "
                "connect-src 'self' wss: https:; "
                "frame-ancestors 'none';"
            )

        # HSTS (仅生产环境 HTTPS)
        if settings.ENVIRONMENT == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"

        return response


# ============================================
# 异常处理中间件
# ============================================

class ExceptionHandlerMiddleware(BaseHTTPMiddleware):
    """全局异常处理中间件"""

    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.logger = logging.getLogger("api.exception")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            return await call_next(request)
        except HTTPException:
            raise
        except ValueError as e:
            self.logger.warning(f"Validation error: {e}")
            return UTF8JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": str(e),
                    },
                },
            )
        except PermissionError as e:
            self.logger.warning(f"Permission denied: {e}")
            return UTF8JSONResponse(
                status_code=403,
                content={
                    "success": False,
                    "error": {
                        "code": "PERMISSION_DENIED",
                        "message": "Permission denied",
                    },
                },
            )
        except Exception as e:
            request_id = get_request_id()
            self.logger.error(
                f"Unhandled exception: {e}",
                extra={"request_id": request_id},
                exc_info=True,
            )
            return UTF8JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error": {
                        "code": "INTERNAL_SERVER_ERROR",
                        "message": "An unexpected error occurred" if settings.ENVIRONMENT == "production" else str(e),
                        "details": {"request_id": request_id},
                    },
                },
            )


# ============================================
# 服务间认证中间件
# ============================================

class ServiceAuthMiddleware(BaseHTTPMiddleware):
    """内部服务认证中间件"""

    def __init__(self, app: ASGIApp, allowed_paths: Optional[list[str]] = None):
        super().__init__(app)
        self.allowed_paths = allowed_paths or [
            "/health",
            "/metrics",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/api/v1/internal",
        ]

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # 检查是否为内部服务路径
        path = request.url.path
        is_internal = any(path.startswith(p) for p in self.allowed_paths)

        if is_internal and path.startswith("/api/v1/internal"):
            # 验证服务 Token
            auth_header = request.headers.get("Authorization")
            if not auth_header or not auth_header.startswith("Bearer "):
                return UTF8JSONResponse(
                    status_code=401,
                    content={"success": False, "error": {"code": "SERVICE_AUTH_REQUIRED", "message": "Service authentication required"}},
                )

            token = auth_header[7:]  # 去掉 "Bearer "
            if not verify_service_token(token):
                return UTF8JSONResponse(
                    status_code=401,
                    content={"success": False, "error": {"code": "INVALID_SERVICE_TOKEN", "message": "Invalid service token"}},
                )

        return await call_next(request)