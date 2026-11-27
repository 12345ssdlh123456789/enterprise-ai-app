# API Gateway - System Configs Routes

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import get_current_user, get_current_tenant, get_role_permissions, has_permission
from app.db.session import get_async_db
from app.models import SystemConfig, User, Tenant
from app.schemas import (
    SystemConfigSchema,
    SystemConfigUpdate,
    ApiResponse,
    ResponseMeta,
)

router = APIRouter(prefix="/system-configs", tags=["System Configs"])


def create_meta(request: Request) -> ResponseMeta:
    return ResponseMeta(
        request_id=getattr(request.state, "request_id", "unknown"),
        timestamp=datetime.now(timezone.utc),
        version=settings.APP_VERSION,
    )


def config_to_schema(config: SystemConfig) -> SystemConfigSchema:
    return SystemConfigSchema(
        key=config.key,
        value=config.value,
        description=config.description,
        type=config.type.value,
        editable=config.editable,
    )


# ============================================
# 获取所有系统配置 (Super Admin)
# ============================================

@router.get("", response_model=ApiResponse[List[SystemConfigSchema]])
async def list_system_configs(
    request: Request,
    editable_only: bool = Query(False),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """获取所有系统配置 (SUPER_ADMIN)"""
    user_perms = get_role_permissions(current_user.role.value)
    if not has_permission(user_perms, "*:*"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: requires SUPER_ADMIN",
        )

    query = select(SystemConfig)

    if editable_only:
        query = query.where(SystemConfig.editable == True)

    query = query.order_by(SystemConfig.key)

    result = await db.execute(query)
    configs = result.scalars().all()

    return ApiResponse(data=[config_to_schema(c) for c in configs], meta=create_meta(request))


# ============================================
# 获取单个系统配置
# ============================================

@router.get("/{key}", response_model=ApiResponse[SystemConfigSchema])
async def get_system_config(
    request: Request,
    key: str,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """获取单个系统配置 (SUPER_ADMIN)"""
    user_perms = get_role_permissions(current_user.role.value)
    if not has_permission(user_perms, "*:*"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: requires SUPER_ADMIN",
        )

    result = await db.execute(select(SystemConfig).where(SystemConfig.key == key))
    config = result.scalar_one_or_none()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="System config not found",
        )

    return ApiResponse(data=config_to_schema(config), meta=create_meta(request))


# ============================================
# 更新系统配置
# ============================================

@router.patch("/{key}", response_model=ApiResponse[SystemConfigSchema])
async def update_system_config(
    request: Request,
    key: str,
    config_data: SystemConfigUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """更新系统配置 (SUPER_ADMIN)"""
    user_perms = get_role_permissions(current_user.role.value)
    if not has_permission(user_perms, "*:*"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: requires SUPER_ADMIN",
        )

    result = await db.execute(select(SystemConfig).where(SystemConfig.key == key))
    config = result.scalar_one_or_none()

    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="System config not found",
        )

    if not config.editable:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This config is not editable",
        )

    config.value = config_data.value
    await db.commit()
    await db.refresh(config)

    return ApiResponse(data=config_to_schema(config), meta=create_meta(request))


# ============================================
# 获取租户可编辑配置 (租户管理员)
# ============================================

@router.get("/tenant/editable", response_model=ApiResponse[List[SystemConfigSchema]])
async def list_tenant_editable_configs(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """获取租户可编辑的系统配置 (租户管理员)"""
    user_perms = get_role_permissions(current_user.role.value)
    if not has_permission(user_perms, "tenant:update"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: tenant:update",
        )

    result = await db.execute(
        select(SystemConfig).where(SystemConfig.editable == True).order_by(SystemConfig.key)
    )
    configs = result.scalars().all()

    return ApiResponse(data=[config_to_schema(c) for c in configs], meta=create_meta(request))
