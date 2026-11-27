"""业务事件 → 站内通知（文档解析完成/失败、工作流执行结束）。

两个原则：

1. **不影响主流程**：通知是锦上添花，写失败只记日志，绝不能让上传/执行接口 500。
   用独立 session 写入，不掺进调用方的事务（调用方回滚不该把通知也带走）。
2. **两种后端都写对**：`GATEWAY_PROXY_NOTIFICATIONS=false` 时写网关自己的 `notifications` 表；
   打开时 POST 给 notification-service —— 否则列表已经转发到微服务，这条通知在
   `/notifications` 里根本看不到。
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import UUID

import httpx

from app.core.config import settings
from app.core.internal_auth import internal_headers
from app.db.session import AsyncSessionLocal
from app.models import Notification, NotificationChannel, NotificationType

logger = logging.getLogger(__name__)

_CREATE_PATH = "/api/v1/notifications"


async def notify(
    *,
    tenant_id: UUID,
    user_id: Optional[UUID],
    title: str,
    content: str,
    type: NotificationType = NotificationType.INFO,
    data: Optional[dict[str, Any]] = None,
) -> None:
    """给某个用户写一条站内通知；任何异常都只记日志，不向上抛。"""
    if user_id is None:
        # 列表按 user_id 过滤，没有归属人的通知谁也看不到
        return

    payload = {
        "user_id": str(user_id),
        "type": type.value if isinstance(type, NotificationType) else str(type),
        "channel": NotificationChannel.IN_APP.value,
        "title": title[:255],
        "content": content,
        "data": data,
    }

    try:
        if settings.GATEWAY_PROXY_NOTIFICATIONS:
            await _send_to_service(tenant_id, user_id, payload)
        else:
            await _write_local(tenant_id, user_id, payload)
    except Exception:
        logger.warning("写入通知失败（不影响主流程）：%s", title, exc_info=True)


async def _write_local(tenant_id: UUID, user_id: UUID, payload: dict) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            Notification(
                tenant_id=tenant_id,
                user_id=user_id,
                type=NotificationType(payload["type"]),
                channel=NotificationChannel.IN_APP,
                title=payload["title"],
                content=payload["content"],
                data=payload["data"],
            )
        )
        await db.commit()


async def _send_to_service(tenant_id: UUID, user_id: UUID, payload: dict) -> None:
    headers = internal_headers("POST", _CREATE_PATH, str(tenant_id), str(user_id))
    headers["content-type"] = "application/json"
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.post(
            settings.NOTIFICATION_SERVICE_URL.rstrip("/") + _CREATE_PATH,
            json=payload,
            headers=headers,
        )
    if resp.status_code >= 300:
        logger.warning(
            "notification-service 拒绝写入通知：%s %s", resp.status_code, resp.text[:200]
        )
