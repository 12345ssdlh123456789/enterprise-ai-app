# API Gateway - API Keys Routes

from uuid import UUID
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import get_current_user, get_current_tenant, get_role_permissions, has_permission, generate_api_key
from app.db.session import get_async_db
from app.models import APIKey, User, Tenant
from app.schemas import (
    APIKeyCreate,
    APIKeyResponse,
    APIKeyListItem,
    PaginationParams,
    PaginatedResponse,
    ApiResponse,
    ResponseMeta,
)

router = APIRouter(prefix="/api-keys", tags=["API Keys"])


def create_meta(request: Request) -> ResponseMeta:
    return ResponseMeta(
        request_id=getattr(request.state, "request_id", "unknown"),
        timestamp=datetime.now(timezone.utc),
        version=settings.APP_VERSION,
    )


def apikey_to_list_item(key: APIKey) -> APIKeyListItem:
    return APIKeyListItem(
        id=key.id,
        key_prefix=key.key_prefix,
        name=key.name,
        permissions=key.permissions,
        expires_at=key.expires_at,
        last_used_at=key.last_used_at,
        created_at=key.created_at,
        revoked_at=key.revoked_at,
    )


# ============================================
# 获取 API Key 列表
# ============================================

@router.get("", response_model=ApiResponse[PaginatedResponse[APIKeyListItem]])
async def list_api_keys(
    request: Request,
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """获取 API Key 列表"""
    user_perms = get_role_permissions(current_user.role.value)
    if not has_permission(user_perms, "user:read"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied",
        )

    query = select(APIKey).where(
        APIKey.tenant_id == current_tenant.id,
        APIKey.revoked_at.is_(None),
    )
    count_query = select(func.count(APIKey.id)).where(
        APIKey.tenant_id == current_tenant.id,
        APIKey.revoked_at.is_(None),
    )

    # 非管理员只能看自己创建的
    if current_user.role.value not in ["SUPER_ADMIN", "ADMIN"]:
        query = query.where(APIKey.created_by == current_user.id)
        count_query = count_query.where(APIKey.created_by == current_user.id)

    query = query.order_by(desc(APIKey.created_at))
    offset = (pagination.page - 1) * pagination.page_size
    query = query.offset(offset).limit(pagination.page_size)

    result = await db.execute(query)
    keys = result.scalars().all()

    count_result = await db.execute(count_query)
    total = count_result.scalar()

    items = [apikey_to_list_item(k) for k in keys]
    paginated = PaginatedResponse.create(items, total, pagination)

    return ApiResponse(data=paginated, meta=create_meta(request))


# ============================================
# 创建 API Key
# ============================================

@router.post("", response_model=ApiResponse[APIKeyResponse], status_code=status.HTTP_201_CREATED)
async def create_api_key(
    request: Request,
    key_data: APIKeyCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """创建 API Key"""
    user_perms = get_role_permissions(current_user.role.value)
    if not has_permission(user_perms, "user:read"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied",
        )

    full_key, key_hash, key_prefix = generate_api_key()

    api_key = APIKey(
        tenant_id=current_tenant.id,
        name=key_data.name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        permissions=key_data.permissions,
        expires_at=key_data.expires_at,
        created_by=current_user.id,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    return ApiResponse(data=APIKeyResponse(
        id=api_key.id,
        key=full_key,  # 仅创建时返回完整 key
        key_prefix=api_key.key_prefix,
        name=api_key.name,
        permissions=api_key.permissions,
        expires_at=api_key.expires_at,
        created_at=api_key.created_at,
    ), meta=create_meta(request))


# ============================================
# 撤销 API Key
# ============================================

@router.delete("/{key_id}", response_model=ApiResponse)
async def revoke_api_key(
    request: Request,
    key_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """撤销 API Key"""
    result = await db.execute(
        select(APIKey).where(
            APIKey.id == key_id,
            APIKey.tenant_id == current_tenant.id,
            APIKey.revoked_at.is_(None),
        )
    )
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API Key not found",
        )

    user_perms = get_role_permissions(current_user.role.value)
    if api_key.created_by != current_user.id and not has_permission(user_perms, "user:update"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied",
        )

    api_key.revoked_at = datetime.now()

    await db.commit()

    return ApiResponse(data={"message": "API Key revoked"}, meta=create_meta(request))
