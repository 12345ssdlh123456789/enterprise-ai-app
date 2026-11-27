# API Gateway - Tenants Routes

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import get_current_user, get_current_tenant, has_permission, get_role_permissions
from app.db.session import get_async_db
from app.models import AuditAction, Tenant, User
from app.services.audit import jsonable, record_audit
from app.schemas import (
    TenantCreate,
    TenantUpdate,
    TenantResponse,
    TenantSettingsSchema,
    ApiResponse,
    ResponseMeta,
)

router = APIRouter(prefix="/tenants", tags=["Tenants"])


def create_meta(request: Request) -> ResponseMeta:
    return ResponseMeta(
        request_id=getattr(request.state, "request_id", "unknown"),
        timestamp=datetime.now(timezone.utc),
        version=settings.APP_VERSION,
    )


# ============================================
# 获取当前租户信息
# ============================================

@router.get("/me", response_model=ApiResponse[TenantResponse])
async def get_current_tenant_info(
    request: Request,
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """获取当前租户信息"""
    tenant_response = TenantResponse(
        id=current_tenant.id,
        name=current_tenant.name,
        slug=current_tenant.slug,
        logo_url=current_tenant.logo_url,
        plan=current_tenant.plan.value,
        settings=current_tenant.settings,
        created_at=current_tenant.created_at,
        updated_at=current_tenant.updated_at,
    )
    return ApiResponse(data=tenant_response, meta=create_meta(request))


# ============================================
# 更新当前租户信息 (管理员)
# ============================================

@router.patch("/me", response_model=ApiResponse[TenantResponse])
async def update_current_tenant(
    request: Request,
    tenant_data: TenantUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """更新当前租户信息 (需要租户更新权限)"""
    user_perms = get_role_permissions(current_user.role.value)
    if not has_permission(user_perms, "tenant:update"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: tenant:update",
        )

    update_data = tenant_data.model_dump(exclude_unset=True)

    # 如果更新 slug，检查唯一性
    if "slug" in update_data:
        result = await db.execute(
            select(Tenant).where(Tenant.slug == update_data["slug"], Tenant.id != current_tenant.id)
        )
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Slug already taken",
            )

    for field, value in update_data.items():
        setattr(current_tenant, field, value)

    await db.commit()
    await db.refresh(current_tenant)

    tenant_response = TenantResponse(
        id=current_tenant.id,
        name=current_tenant.name,
        slug=current_tenant.slug,
        logo_url=current_tenant.logo_url,
        plan=current_tenant.plan.value,
        settings=current_tenant.settings,
        created_at=current_tenant.created_at,
        updated_at=current_tenant.updated_at,
    )

    return ApiResponse(data=tenant_response, meta=create_meta(request))


# ============================================
# 获取租户设置
# ============================================

@router.get("/me/settings", response_model=ApiResponse[TenantSettingsSchema])
async def get_tenant_settings(
    request: Request,
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """获取租户设置"""
    settings_schema = TenantSettingsSchema(**current_tenant.settings)
    return ApiResponse(data=settings_schema, meta=create_meta(request))


# ============================================
# 更新租户设置 (管理员)
# ============================================

@router.patch("/me/settings", response_model=ApiResponse[TenantSettingsSchema])
async def update_tenant_settings(
    request: Request,
    settings_data: TenantSettingsSchema,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """更新租户设置 (需要租户更新权限)"""
    user_perms = get_role_permissions(current_user.role.value)
    if not has_permission(user_perms, "tenant:update"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: tenant:update",
        )

    current_tenant.settings = settings_data.model_dump()
    await db.commit()
    await db.refresh(current_tenant)

    return ApiResponse(data=settings_data, meta=create_meta(request))


# ============================================
# 创建租户 (Super Admin only - 通常用于平台管理)
# ============================================

@router.post("", response_model=ApiResponse[TenantResponse], status_code=status.HTTP_201_CREATED)
async def create_tenant(
    request: Request,
    tenant_data: TenantCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """创建租户 (需要 SUPER_ADMIN 权限)"""
    user_perms = get_role_permissions(current_user.role.value)
    if not has_permission(user_perms, "*:*"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: requires SUPER_ADMIN",
        )

    # 检查 slug 唯一性
    result = await db.execute(select(Tenant).where(Tenant.slug == tenant_data.slug))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Slug already taken",
        )

    tenant = Tenant(
        name=tenant_data.name,
        slug=tenant_data.slug,
        logo_url=tenant_data.logo_url,
        plan=tenant_data.plan,
        settings=tenant_data.settings or {},
    )
    db.add(tenant)
    await db.flush()

    await record_audit(
        db,
        tenant_id=tenant.id,
        user_id=current_user.id,
        action=AuditAction.CREATE,
        resource="tenant",
        resource_id=tenant.id,
        new_value={"name": tenant.name, "slug": tenant.slug, "plan": jsonable(tenant.plan)},
        request=request,
    )

    await db.commit()
    await db.refresh(tenant)

    tenant_response = TenantResponse(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        logo_url=tenant.logo_url,
        plan=tenant.plan.value,
        settings=tenant.settings,
        created_at=tenant.created_at,
        updated_at=tenant.updated_at,
    )

    return ApiResponse(data=tenant_response, meta=create_meta(request))


# ============================================
# 按 ID 更新租户 (平台管理)
# ============================================

@router.patch("/{tenant_id}", response_model=ApiResponse[TenantResponse])
async def update_tenant_by_id(
    request: Request,
    tenant_id: UUID,
    tenant_data: TenantUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """按租户 ID 更新名称/套餐/设置 (需要 SUPER_ADMIN)"""
    user_perms = get_role_permissions(current_user.role.value)
    if not has_permission(user_perms, "*:*"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: requires SUPER_ADMIN",
        )

    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    update_data = tenant_data.model_dump(exclude_unset=True)

    if "slug" in update_data:
        result = await db.execute(
            select(Tenant).where(Tenant.slug == update_data["slug"], Tenant.id != tenant.id)
        )
        if result.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Slug already taken")

    old_value = {field: jsonable(getattr(tenant, field, None)) for field in update_data}
    for field, value in update_data.items():
        setattr(tenant, field, value)

    await record_audit(
        db,
        tenant_id=tenant.id,
        user_id=current_user.id,
        action=AuditAction.UPDATE,
        resource="tenant",
        resource_id=tenant.id,
        old_value=old_value,
        new_value={field: jsonable(value) for field, value in update_data.items()},
        request=request,
    )

    await db.commit()
    await db.refresh(tenant)

    return ApiResponse(
        data=TenantResponse(
            id=tenant.id,
            name=tenant.name,
            slug=tenant.slug,
            logo_url=tenant.logo_url,
            plan=tenant.plan.value,
            settings=tenant.settings,
            created_at=tenant.created_at,
            updated_at=tenant.updated_at,
        ),
        meta=create_meta(request),
    )


# ============================================
# 获取租户列表 (Super Admin)
# ============================================

@router.get("", response_model=ApiResponse[list[TenantResponse]])
async def list_tenants(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """获取所有租户列表 (SUPER_ADMIN)"""
    user_perms = get_role_permissions(current_user.role.value)
    if not has_permission(user_perms, "*:*"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: requires SUPER_ADMIN",
        )

    result = await db.execute(select(Tenant).order_by(Tenant.created_at.desc()))
    tenants = result.scalars().all()

    tenant_responses = [
        TenantResponse(
            id=t.id,
            name=t.name,
            slug=t.slug,
            logo_url=t.logo_url,
            plan=t.plan.value,
            settings=t.settings,
            created_at=t.created_at,
            updated_at=t.updated_at,
        )
        for t in tenants
    ]

    return ApiResponse(data=tenant_responses, meta=create_meta(request))