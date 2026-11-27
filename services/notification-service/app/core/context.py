"""请求上下文：从网关传入的请求头解析租户 / 用户，未传时回退到本地演示身份。

微服务独立运行时没有鉴权，网关（或前端调试）通过 `X-Tenant-Id` / `X-User-Id`
注入已认证身份；两者都必须能解析成 UUID，否则直接 400，避免静默写到演示租户。

通知服务比文档服务多一层语义：`user_id` 不只是「操作人」，还是**收件人**。
网关转发时这两个 ID 都来自 JWT，所以列表/已读/删除只能碰到当前用户自己的通知。
"""

import json
from contextvars import ContextVar
from uuid import UUID

DEMO_TENANT_ID = UUID("00000000-0000-0000-0000-000000000001")
DEMO_USER_ID = UUID("00000000-0000-0000-0000-000000000001")

_tenant_id: ContextVar[UUID] = ContextVar("tenant_id", default=DEMO_TENANT_ID)
_user_id: ContextVar[UUID] = ContextVar("user_id", default=DEMO_USER_ID)

_TENANT_HEADER = b"x-tenant-id"
_USER_HEADER = b"x-user-id"


def current_tenant_id() -> UUID:
    """当前请求的租户 ID（独立运行且未带头时是演示租户）。"""
    return _tenant_id.get()


def current_user_id() -> UUID:
    """当前请求的用户 ID（独立运行且未带头时是演示用户）。"""
    return _user_id.get()


class TenantContextMiddleware:
    """纯 ASGI 中间件：把 X-Tenant-Id / X-User-Id 写进 contextvar，请求结束即复位。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict((key.lower(), value) for key, value in scope.get("headers") or [])
        try:
            tenant_id = (
                UUID(headers[_TENANT_HEADER].decode())
                if _TENANT_HEADER in headers
                else DEMO_TENANT_ID
            )
            user_id = UUID(headers[_USER_HEADER].decode()) if _USER_HEADER in headers else DEMO_USER_ID
        except ValueError:
            body = json.dumps(
                {"detail": "X-Tenant-Id / X-User-Id 必须是合法的 UUID"}, ensure_ascii=False
            ).encode("utf-8")
            await send(
                {
                    "type": "http.response.start",
                    "status": 400,
                    "headers": [
                        (b"content-type", b"application/json; charset=utf-8"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        tenant_token = _tenant_id.set(tenant_id)
        user_token = _user_id.set(user_id)
        try:
            await self.app(scope, receive, send)
        finally:
            _tenant_id.reset(tenant_token)
            _user_id.reset(user_token)
