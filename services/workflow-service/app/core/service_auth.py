"""服务间调用的请求签名（HMAC-SHA256）。

背景：微服务原先无条件信任 `X-Tenant-Id` / `X-User-Id`，任何能直连端口的人都能
冒充任意租户。现在调用方（网关转发、或微服务互调）必须带两个头：

    X-Service-Timestamp: <unix 秒>
    X-Service-Signature: hex(hmac_sha256(SERVICE_API_KEY, canonical))

    canonical = METHOD \\n PATH \\n tenant \\n user \\n timestamp

`SERVICE_API_KEY` 为空表示**本地开发模式**：不校验签名（启动日志会提示）。
一旦配置，所有 /api/v1/* 请求都必须带签名，缺失 / 过期 / 不匹配一律 401；
`/health`、`/ready`、`/metrics`、`/docs`、`/openapi.json` 不受限制（探针与文档）。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

from app.core.config import settings

SIGNATURE_HEADER = b"x-service-signature"
TIMESTAMP_HEADER = b"x-service-timestamp"
TENANT_HEADER = b"x-tenant-id"
USER_HEADER = b"x-user-id"

MAX_SKEW_SECONDS = 300
EXEMPT_PREFIXES = ("/health", "/ready", "/metrics", "/docs", "/redoc", "/openapi.json")


def service_api_key() -> str:
    """读取服务间共享密钥；兼容各服务 Settings 里大写/小写两种字段命名。"""
    key = getattr(settings, "SERVICE_API_KEY", "") or getattr(settings, "service_api_key", "")
    return key or ""


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def canonical_string(method: str, path: str, tenant_id: str, user_id: str, timestamp) -> str:
    return "\n".join([method.upper(), path, tenant_id or "", user_id or "", str(timestamp)])


def sign_request(
    service_key: str,
    method: str,
    path: str,
    tenant_id: str = "",
    user_id: str = "",
    timestamp=None,
) -> dict:
    """生成调用方应带的两个头。timestamp 便于测试构造过期签名。"""
    ts = str(int(timestamp if timestamp is not None else time.time()))
    mac = hmac.new(
        service_key.encode("utf-8"),
        canonical_string(method, path, tenant_id, user_id, ts).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {"X-Service-Timestamp": ts, "X-Service-Signature": mac}


def verify_signature(service_key: str, headers: dict, method: str, path: str) -> str | None:
    """校验签名：通过返回 None，失败返回可读的原因。"""
    raw_ts = headers.get(TIMESTAMP_HEADER)
    raw_sig = headers.get(SIGNATURE_HEADER)
    if not raw_ts or not raw_sig:
        return "缺少服务间签名（需要 X-Service-Timestamp 与 X-Service-Signature）"
    try:
        ts = int(_text(raw_ts))
    except (TypeError, ValueError):
        return "X-Service-Timestamp 不是合法的 unix 秒"

    if abs(int(time.time()) - ts) > MAX_SKEW_SECONDS:
        return f"签名已过期（允许时差 {MAX_SKEW_SECONDS} 秒），请检查服务端时钟"

    tenant = _text(headers.get(TENANT_HEADER))
    user = _text(headers.get(USER_HEADER))
    expected = hmac.new(
        service_key.encode("utf-8"),
        canonical_string(method, path, tenant, user, ts).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, _text(raw_sig)):
        return "签名不匹配（SERVICE_API_KEY 不一致，或请求头被篡改）"
    return None


async def _send_unauthorized(send, detail: str) -> None:
    body = json.dumps({"detail": detail}, ensure_ascii=False).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class ServiceAuthMiddleware:
    """纯 ASGI 中间件：校验服务间签名。应注册在 TenantContextMiddleware 外层。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        key = service_api_key()
        path = scope.get("path", "") or ""
        exempt = any(path == prefix or path.startswith(prefix + "/") for prefix in EXEMPT_PREFIXES)

        if key and not exempt:
            headers = {k.lower(): v for k, v in (scope.get("headers") or [])}
            error = verify_signature(key, headers, scope.get("method", "GET"), path)
            if error:
                await _send_unauthorized(send, error)
                return

        await self.app(scope, receive, send)
