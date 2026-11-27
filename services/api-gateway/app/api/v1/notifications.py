# API Gateway - Notifications Routes

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from datetime import datetime, timezone
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import get_current_user, get_current_tenant, get_role_permissions, has_permission
from app.db.session import get_async_db
from app.models import Notification, User, Tenant
from app.schemas import (
    NotificationSchema,
    NotificationCreate,
    PaginationParams,
    PaginatedResponse,
    ApiResponse,
    ResponseMeta,
)

router = APIRouter(prefix="/notifications", tags=["Notifications"])


def create_meta(request: Request) -> ResponseMeta:
    return ResponseMeta(
        request_id=getattr(request.state, "request_id", "unknown"),
        timestamp=datetime.now(timezone.utc),
        version=settings.APP_VERSION,
    )


def notif_to_schema(notif: Notification) -> NotificationSchema:
    return NotificationSchema(
        id=notif.id,
        tenant_id=notif.tenant_id,
        user_id=notif.user_id,
        type=notif.type.value,
        channel=notif.channel.value,
        title=notif.title,
        content=notif.content,
        data=notif.data,
        read=notif.read,
        sent_at=notif.sent_at,
        created_at=notif.created_at,
    )


# ============================================
# 获取通知列表
# ============================================

@router.get("", response_model=ApiResponse[PaginatedResponse[NotificationSchema]])
async def list_notifications(
    request: Request,
    pagination: PaginationParams = Depends(),
    unread_only: bool = Query(False, description="仅未读"),
    type: Optional[str] = Query(None, description="按类型筛选"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """获取当前用户的通知列表"""
    query = select(Notification).where(
        Notification.tenant_id == current_tenant.id,
        Notification.user_id == current_user.id,
    )
    count_query = select(func.count(Notification.id)).where(
        Notification.tenant_id == current_tenant.id,
        Notification.user_id == current_user.id,
    )

    if unread_only:
        query = query.where(Notification.read == False)
        count_query = count_query.where(Notification.read == False)

    if type:
        query = query.where(Notification.type == type)
        count_query = count_query.where(Notification.type == type)

    query = query.order_by(desc(Notification.created_at))
    offset = (pagination.page - 1) * pagination.page_size
    query = query.offset(offset).limit(pagination.page_size)

    result = await db.execute(query)
    notifs = result.scalars().all()

    count_result = await db.execute(count_query)
    total = count_result.scalar()

    items = [notif_to_schema(n) for n in notifs]
    paginated = PaginatedResponse.create(items, total, pagination)

    return ApiResponse(data=paginated, meta=create_meta(request))


# ============================================
# 标记已读
# ============================================

@router.patch("/{notif_id}/read", response_model=ApiResponse[NotificationSchema])
async def mark_notification_read(
    request: Request,
    notif_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """标记通知为已读"""
    result = await db.execute(
        select(Notification).where(
            Notification.id == notif_id,
            Notification.tenant_id == current_tenant.id,
            Notification.user_id == current_user.id,
        )
    )
    notif = result.scalar_one_or_none()

    if not notif:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )

    notif.read = True
    await db.commit()
    await db.refresh(notif)

    return ApiResponse(data=notif_to_schema(notif), meta=create_meta(request))


# ============================================
# 全部标记已读
# ============================================

@router.patch("/read-all", response_model=ApiResponse)
async def mark_all_read(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """将所有通知标记为已读"""
    result = await db.execute(
        select(Notification).where(
            Notification.tenant_id == current_tenant.id,
            Notification.user_id == current_user.id,
            Notification.read == False,
        )
    )
    for notif in result.scalars().all():
        notif.read = True

    await db.commit()

    return ApiResponse(data={"message": "All notifications marked as read"}, meta=create_meta(request))


# ============================================
# 删除通知
# ============================================

@router.delete("/{notif_id}", response_model=ApiResponse)
async def delete_notification(
    request: Request,
    notif_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """删除通知"""
    result = await db.execute(
        select(Notification).where(
            Notification.id == notif_id,
            Notification.tenant_id == current_tenant.id,
            Notification.user_id == current_user.id,
        )
    )
    notif = result.scalar_one_or_none()

    if not notif:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )

    await db.delete(notif)
    await db.commit()

    return ApiResponse(data={"message": "Notification deleted"}, meta=create_meta(request))


# ============================================
# 获取未读数量
# ============================================

@router.get("/unread-count", response_model=ApiResponse)
async def get_unread_count(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """获取未读通知数量"""
    count_result = await db.execute(
        select(func.count(Notification.id)).where(
            Notification.tenant_id == current_tenant.id,
            Notification.user_id == current_user.id,
            Notification.read == False,
        )
    )
    count = count_result.scalar()

    return ApiResponse(data={"unread_count": count}, meta=create_meta(request))


# ============================================
# 创建通知 (管理员/系统)
# ============================================

@router.post("", response_model=ApiResponse[NotificationSchema], status_code=status.HTTP_201_CREATED)
async def create_notification(
    request: Request,
    notif_data: NotificationCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """创建通知 (管理员或系统调用)"""
    user_perms = get_role_permissions(current_user.role.value)
    if not has_permission(user_perms, "*:*") and current_user.role.value not in ["SUPER_ADMIN", "ADMIN"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: requires admin",
        )

    notif = Notification(
        tenant_id=current_tenant.id,
        # 不传 user_id 时默认发给自己：原来直接写 None，而列表按 user_id 过滤，
        # 结果这条通知谁也看不到（转发模式下 notification-service 就是这么做的，这里对齐）。
        user_id=notif_data.user_id or current_user.id,
        type=notif_data.type,
        channel=notif_data.channel,
        title=notif_data.title,
        content=notif_data.content,
        data=notif_data.data,
    )
    db.add(notif)
    await db.commit()
    await db.refresh(notif)

    # TODO: 根据 channel 发送实际通知 (邮件、Webhook、Slack 等)

    return ApiResponse(data=notif_to_schema(notif), meta=create_meta(request))
