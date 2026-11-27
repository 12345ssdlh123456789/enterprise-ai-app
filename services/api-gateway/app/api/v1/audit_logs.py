# API Gateway - Audit Logs Routes

from typing import Optional, List
from uuid import UUID
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import get_current_user, get_current_tenant, get_role_permissions, has_permission
from app.db.session import get_async_db
from app.models import AuditLog, User, Tenant
from app.schemas import (
    AuditLogSchema,
    PaginationParams,
    PaginatedResponse,
    ApiResponse,
    ResponseMeta,
)

router = APIRouter(prefix="/audit-logs", tags=["Audit Logs"])


def create_meta(request: Request) -> ResponseMeta:
    return ResponseMeta(
        request_id=getattr(request.state, "request_id", "unknown"),
        timestamp=datetime.now(timezone.utc),
        version=settings.APP_VERSION,
    )


def audit_to_schema(log: AuditLog) -> AuditLogSchema:
    return AuditLogSchema(
        id=log.id,
        tenant_id=log.tenant_id,
        user_id=log.user_id,
        action=log.action.value,
        resource=log.resource,
        resource_id=log.resource_id,
        old_value=log.old_value,
        new_value=log.new_value,
        ip_address=str(log.ip_address) if log.ip_address else None,
        user_agent=log.user_agent,
        success=log.success,
        error_message=log.error_message,
        created_at=log.created_at,
    )


# ============================================
# 获取审计日志列表 (管理员)
# ============================================

@router.get("", response_model=ApiResponse[PaginatedResponse[AuditLogSchema]])
async def list_audit_logs(
    request: Request,
    pagination: PaginationParams = Depends(),
    action: Optional[str] = Query(None, description="按动作筛选"),
    resource: Optional[str] = Query(None, description="按资源筛选"),
    user_id: Optional[UUID] = Query(None, description="按用户筛选"),
    success: Optional[bool] = Query(None, description="按成功/失败筛选"),
    start_date: Optional[datetime] = Query(None, description="开始日期"),
    end_date: Optional[datetime] = Query(None, description="结束日期"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """获取审计日志列表 (需要管理员权限)"""
    user_perms = get_role_permissions(current_user.role.value)
    if not has_permission(user_perms, "audit:read") and current_user.role.value not in ["SUPER_ADMIN", "ADMIN"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: requires admin",
        )

    query = select(AuditLog).where(AuditLog.tenant_id == current_tenant.id)
    count_query = select(func.count(AuditLog.id)).where(AuditLog.tenant_id == current_tenant.id)

    if action:
        query = query.where(AuditLog.action == action)
        count_query = count_query.where(AuditLog.action == action)

    if resource:
        query = query.where(AuditLog.resource == resource)
        count_query = count_query.where(AuditLog.resource == resource)

    if user_id:
        query = query.where(AuditLog.user_id == user_id)
        count_query = count_query.where(AuditLog.user_id == user_id)

    if success is not None:
        query = query.where(AuditLog.success == success)
        count_query = count_query.where(AuditLog.success == success)

    if start_date:
        query = query.where(AuditLog.created_at >= start_date)
        count_query = count_query.where(AuditLog.created_at >= start_date)

    if end_date:
        query = query.where(AuditLog.created_at <= end_date)
        count_query = count_query.where(AuditLog.created_at <= end_date)

    query = query.order_by(desc(AuditLog.created_at))
    offset = (pagination.page - 1) * pagination.page_size
    query = query.offset(offset).limit(pagination.page_size)

    result = await db.execute(query)
    logs = result.scalars().all()

    count_result = await db.execute(count_query)
    total = count_result.scalar()

    items = [audit_to_schema(log) for log in logs]
    paginated = PaginatedResponse.create(items, total, pagination)

    return ApiResponse(data=paginated, meta=create_meta(request))


# ============================================
# 获取资源的审计历史
# ============================================

@router.get("/resource/{resource}/{resource_id}", response_model=ApiResponse[List[AuditLogSchema]])
async def get_resource_audit_logs(
    request: Request,
    resource: str,
    resource_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """获取特定资源的审计历史"""
    user_perms = get_role_permissions(current_user.role.value)
    if not has_permission(user_perms, "audit:read") and current_user.role.value not in ["SUPER_ADMIN", "ADMIN"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: requires admin",
        )

    result = await db.execute(
        select(AuditLog)
        .where(
            AuditLog.tenant_id == current_tenant.id,
            AuditLog.resource == resource,
            AuditLog.resource_id == resource_id,
        )
        .order_by(desc(AuditLog.created_at))
        .limit(limit)
    )
    logs = result.scalars().all()

    return ApiResponse(data=[audit_to_schema(log) for log in logs], meta=create_meta(request))


# ============================================
# 导出审计日志 (CSV)
# ============================================

@router.get("/export", response_model=None)
async def export_audit_logs(
    request: Request,
    action: Optional[str] = Query(None),
    resource: Optional[str] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """导出审计日志为 CSV"""
    user_perms = get_role_permissions(current_user.role.value)
    if not has_permission(user_perms, "audit:read") and current_user.role.value not in ["SUPER_ADMIN", "ADMIN"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: requires admin",
        )

    query = select(AuditLog).where(AuditLog.tenant_id == current_tenant.id)

    if action:
        query = query.where(AuditLog.action == action)
    if resource:
        query = query.where(AuditLog.resource == resource)
    if start_date:
        query = query.where(AuditLog.created_at >= start_date)
    if end_date:
        query = query.where(AuditLog.created_at <= end_date)

    query = query.order_by(desc(AuditLog.created_at)).limit(10000)

    result = await db.execute(query)
    logs = result.scalars().all()

    # 生成 CSV
    import csv
    import io
    from fastapi.responses import StreamingResponse

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Timestamp", "User ID", "Action", "Resource", "Resource ID",
        "Success", "Error", "IP Address", "User Agent"
    ])

    for log in logs:
        writer.writerow([
            str(log.id),
            log.created_at.isoformat(),
            str(log.user_id) if log.user_id else "",
            log.action.value,
            log.resource,
            str(log.resource_id) if log.resource_id else "",
            "Yes" if log.success else "No",
            log.error_message or "",
            str(log.ip_address) if log.ip_address else "",
            log.user_agent or "",
        ])

    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="audit_logs_{datetime.now().strftime("%Y%m%d")}.csv"'},
    )
