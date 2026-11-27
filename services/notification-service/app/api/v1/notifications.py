"""Notification Service 通知 API。

与网关的 `/api/v1/notifications` 同一套契约（UUID 主键、`user_id` 收件人、`title` / `data` / `read`），
网关转发时通过 `X-Tenant-Id` / `X-User-Id` 注入身份（见 `app/core/context.py`）。

所有读写都限定在**当前请求用户**：直连 8006 也不能读到别人的通知。
路由顺序有讲究：`/notifications/unread-count`、`/notifications/read-all` 必须声明在
`/notifications/{notification_id}` 之前，否则会被当成 UUID 解析成 422。
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import current_tenant_id, current_user_id
from app.db.session import get_session
from app.models.notification import Notification
from app.schemas.notification import (
    NotificationCreate,
    NotificationList,
    NotificationResponse,
)

router = APIRouter()


def _user_scope(user_id: Optional[UUID] = None):
    """当前用户的通知范围；`user_id` 只用于同一用户显式筛选。"""
    return Notification.user_id == (user_id or current_user_id())


@router.post(
    "/notifications",
    response_model=NotificationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_notification(
    notif_in: NotificationCreate,
    session: AsyncSession = Depends(get_session),
):
    notif = Notification(
        tenant_id=notif_in.tenant_id or current_tenant_id(),
        user_id=notif_in.user_id or current_user_id(),
        type=notif_in.type,
        channel=notif_in.channel,
        title=notif_in.resolved_title(),
        content=notif_in.content,
        data=notif_in.data,
        recipient_id=notif_in.recipient_id,
        recipient_type=notif_in.recipient_type,
        status="pending",
    )
    session.add(notif)
    await session.commit()
    await session.refresh(notif)
    return notif


@router.get("/notifications", response_model=NotificationList)
async def list_notifications(
    response: Response,
    recipient_id: Optional[str] = None,
    user_id: Optional[UUID] = None,
    unread_only: bool = False,
    type: Optional[str] = Query(None, description="按类型筛选"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    conditions = [_user_scope(user_id)]
    if recipient_id:
        conditions.append(Notification.recipient_id == recipient_id)
    if unread_only:
        conditions.append(Notification.read == False)  # noqa: E712 - SQLAlchemy 过滤器
    if type:
        conditions.append(Notification.type == type)

    total = (
        await session.execute(select(func.count(Notification.id)).where(*conditions))
    ).scalar() or 0

    result = await session.execute(
        select(Notification)
        .where(*conditions)
        .order_by(Notification.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = result.scalars().all()

    # 网关转发靠这个头拼分页（与 document-service 的做法一致）
    response.headers["X-Total-Count"] = str(total)
    return {"items": items, "total": total}


@router.get("/notifications/unread-count")
async def unread_count(
    user_id: Optional[UUID] = None,
    session: AsyncSession = Depends(get_session),
):
    total = (
        await session.execute(
            select(func.count(Notification.id)).where(
                _user_scope(user_id), Notification.read == False  # noqa: E712
            )
        )
    ).scalar() or 0
    return {"unread_count": total}


@router.patch("/notifications/read-all")
async def mark_all_read(
    user_id: Optional[UUID] = None,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Notification).where(_user_scope(user_id), Notification.read == False)  # noqa: E712
    )
    now = datetime.utcnow()
    updated = 0
    for notif in result.scalars().all():
        notif.read = True
        notif.read_at = now
        notif.status = "read"
        updated += 1
    await session.commit()
    return {"updated": updated}


@router.get("/notifications/{notification_id}", response_model=NotificationResponse)
async def get_notification(
    notification_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Notification).where(Notification.id == notification_id, _user_scope())
    )
    notif = result.scalar_one_or_none()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    return notif


@router.post("/notifications/{notification_id}/read")
@router.patch("/notifications/{notification_id}/read")
async def mark_as_read(
    notification_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    """标记单条已读。POST 是旧调用方用的，PATCH 与网关的 `/notifications/{id}/read` 对齐。"""
    result = await session.execute(
        select(Notification).where(Notification.id == notification_id, _user_scope())
    )
    notif = result.scalar_one_or_none()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    notif.read = True
    notif.read_at = datetime.utcnow()
    notif.status = "read"
    await session.commit()
    return {"status": "read", "id": str(notif.id)}


@router.delete("/notifications/{notification_id}")
async def delete_notification(
    notification_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(Notification).where(Notification.id == notification_id, _user_scope())
    )
    notif = result.scalar_one_or_none()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    await session.delete(notif)
    await session.commit()
    return {"status": "deleted"}
