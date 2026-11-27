"""网关 → notification-service 转发。

通知曾经是「不可拆」的典型（`docs/architecture/service-split.md` §5.1）：网关是 UUID 主键 +
`user_id / title / data / read`，notification-service 是 `int` 主键 + `recipient_id / subject`，
假造 UUID 会让「已读 / 删除」按 ID 找不到记录。第 26 轮把 notification-service 的契约改成与网关
一致（迁移 `002_gateway_contract`），现在可以按「数据归 notification-service」整体转发了。

身份：网关先验 JWT，再用 `internal_headers()` 签名并注入 `X-Tenant-Id` / `X-User-Id`；
微服务只返回**当前用户**的通知，转发层不需要再做归属过滤。
权限：与网关自带的通知路由保持一致 —— 只有「创建」要求管理员，其余登录即可。

只在 `GATEWAY_PROXY_NOTIFICATIONS=true` 时注册（见 `app/main.py`）。默认关闭，因为网关 SQLite
与微服务 SQLite 是两套库，打开后演示数据不会自动迁移。
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from app.api.v1 import proxy_adapters as adapt
from app.api.v1.proxy import _gateway_json, _json_body, _send, _upstream_error
from app.core.config import settings
from app.core.security import get_current_user
from app.models import User

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Gateway Proxy"])

_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]
_DEFAULT_PAGE_SIZE = 20
_PROXY = "notification-service"


def _json(payload, status_code: int = 200):
    return _gateway_json(payload, status_code, proxy_name=_PROXY)


def _error(upstream):
    return _upstream_error(upstream, proxy_name=_PROXY)


async def _call(
    request: Request,
    user: User,
    *,
    method: str,
    path: str,
    query: list | None = None,
    payload: dict | None = None,
):
    body = (
        json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    )
    return await _send(
        request,
        user,
        method=method,
        path=path,
        query=query,
        body=body,
        headers={"content-type": "application/json"},
        base_url=settings.NOTIFICATION_SERVICE_URL,
    )


def _page_params(request: Request) -> tuple[int, int]:
    params = request.query_params
    try:
        page = max(1, int(params.get("page") or 1))
        page_size = max(1, int(params.get("page_size") or _DEFAULT_PAGE_SIZE))
    except ValueError:
        raise HTTPException(status_code=422, detail="page / page_size 必须是整数")
    return page, page_size


async def _list_notifications(request: Request, user: User) -> Response:
    page, page_size = _page_params(request)
    params = request.query_params
    query: list[tuple[str, str]] = [("page", str(page)), ("page_size", str(page_size))]
    if str(params.get("unread_only")).lower() in ("1", "true", "yes"):
        query.append(("unread_only", "true"))
    if params.get("type"):
        query.append(("type", params["type"]))

    upstream = await _call(request, user, method="GET", path="/api/v1/notifications", query=query)
    if upstream.status_code >= 400:
        return _error(upstream)

    data = _json_body(upstream)
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise HTTPException(status_code=502, detail="notification-service 列表格式异常")
    try:
        total = int(upstream.headers.get("x-total-count", data.get("total", len(data["items"]))))
    except ValueError:
        total = len(data["items"])

    items = [adapt.to_gateway_notification(item) for item in data["items"]]
    return _json(adapt.envelope(adapt.paginated(items, total, page, page_size)))


async def _create_notification(request: Request, user: User) -> Response:
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if role not in ("SUPER_ADMIN", "ADMIN"):
        raise HTTPException(status_code=403, detail="权限不足：只有管理员可以创建通知")

    try:
        payload = json.loads(await request.body() or b"{}")
    except (ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=422, detail="请求体必须是 JSON 对象")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="请求体必须是 JSON 对象")

    upstream = await _call(
        request,
        user,
        method="POST",
        path="/api/v1/notifications",
        payload=adapt.notification_create_payload_to_ms(payload),
    )
    if upstream.status_code >= 400:
        return _error(upstream)
    return _json(
        adapt.envelope(adapt.to_gateway_notification(_json_body(upstream))),
        status_code=upstream.status_code,
    )


async def _mark_read(request: Request, user: User, notif_id: str) -> Response:
    upstream = await _call(
        request, user, method="PATCH", path=f"/api/v1/notifications/{notif_id}/read"
    )
    if upstream.status_code >= 400:
        return _error(upstream)

    # 网关的 PATCH /{id}/read 返回更新后的通知本体，微服务只返回 {status, id}，这里补一次读
    detail = await _call(request, user, method="GET", path=f"/api/v1/notifications/{notif_id}")
    if detail.status_code >= 400:
        return _error(detail)
    return _json(adapt.envelope(adapt.to_gateway_notification(_json_body(detail))))


async def _mark_all_read(request: Request, user: User) -> Response:
    upstream = await _call(request, user, method="PATCH", path="/api/v1/notifications/read-all")
    if upstream.status_code >= 400:
        return _error(upstream)
    return _json(adapt.envelope({"message": "All notifications marked as read"}))


async def _unread_count(request: Request, user: User) -> Response:
    upstream = await _call(request, user, method="GET", path="/api/v1/notifications/unread-count")
    if upstream.status_code >= 400:
        return _error(upstream)
    data = _json_body(upstream)
    count = data.get("unread_count", 0) if isinstance(data, dict) else 0
    return _json(adapt.envelope({"unread_count": count}))


async def _delete(request: Request, user: User, notif_id: str) -> Response:
    upstream = await _call(
        request, user, method="DELETE", path=f"/api/v1/notifications/{notif_id}"
    )
    if upstream.status_code >= 400:
        return _error(upstream)
    return _json(adapt.envelope({"message": "Notification deleted"}))


async def _dispatch(request: Request, user: User) -> Response:
    path = request.url.path.rstrip("/") or "/api/v1/notifications"
    method = request.method.upper()

    if path == "/api/v1/notifications" and method == "GET":
        return await _list_notifications(request, user)
    if path == "/api/v1/notifications" and method == "POST":
        return await _create_notification(request, user)
    if path == "/api/v1/notifications/unread-count" and method == "GET":
        return await _unread_count(request, user)
    if path == "/api/v1/notifications/read-all" and method in ("PATCH", "POST"):
        return await _mark_all_read(request, user)

    if path.startswith("/api/v1/notifications/"):
        rest = path[len("/api/v1/notifications/") :]
        notif_id, _, suffix = rest.partition("/")
        if suffix == "read" and method in ("PATCH", "POST"):
            return await _mark_read(request, user, notif_id)
        if not suffix and method == "DELETE":
            return await _delete(request, user, notif_id)

    return _json(
        adapt.error_envelope(
            f"转发模式暂不支持该通知接口：{method} {path}", code="NOT_IMPLEMENTED"
        ),
        status_code=501,
    )


@router.api_route("/notifications", methods=_METHODS, include_in_schema=False)
@router.api_route("/notifications/{path:path}", methods=_METHODS, include_in_schema=False)
async def proxy_notifications(request: Request, user: User = Depends(get_current_user)):
    return await _dispatch(request, user)
