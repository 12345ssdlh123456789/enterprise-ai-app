# API Gateway - Users Routes

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import get_current_user, get_current_tenant, has_permission, get_role_permissions
from app.db.session import get_async_db
from app.models import AuditAction, User, Tenant
from app.services.audit import record_audit
from app.schemas import (
    UserCreate,
    UserUpdate,
    UserResponse,
    UserListResponse,
    PaginationParams,
    PaginatedResponse,
    ApiResponse,
    ResponseMeta,
)

router = APIRouter(prefix="/users", tags=["Users"])


# ============================================
# 辅助函数
# ============================================

def _jsonable(value):
    """把枚举 / UUID 等转成可写进 JSON 列的值。"""
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def create_meta(request: Request) -> ResponseMeta:
    return ResponseMeta(
        request_id=getattr(request.state, "request_id", "unknown"),
        timestamp=datetime.now(timezone.utc),  # 这里用 version 作为时间戳占位
        version=settings.APP_VERSION,
    )


def user_to_list_item(user: User) -> UserListResponse:
    return UserListResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        role=user.role.value,
        status=user.status.value,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


# ============================================
# 获取用户列表 (管理员)
# ============================================

@router.get("", response_model=ApiResponse[PaginatedResponse[UserListResponse]])
async def list_users(
    request: Request,
    pagination: PaginationParams = Depends(),
    search: Optional[str] = Query(None, description="搜索邮箱、用户名、显示名"),
    role: Optional[str] = Query(None, description="按角色筛选"),
    status: Optional[str] = Query(None, description="按状态筛选"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """获取租户内用户列表 (需要用户读取权限)"""
    # 权限检查
    user_perms = get_role_permissions(current_user.role.value)
    if not has_permission(user_perms, "user:read"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: user:read",
        )

    # 构建查询
    query = select(User).where(User.tenant_id == current_tenant.id, User.deleted_at.is_(None))
    count_query = select(func.count(User.id)).where(User.tenant_id == current_tenant.id, User.deleted_at.is_(None))

    # 搜索
    if search:
        search_term = f"%{search}%"
        query = query.where(
            or_(
                User.email.ilike(search_term),
                User.username.ilike(search_term),
                User.display_name.ilike(search_term),
            )
        )
        count_query = count_query.where(
            or_(
                User.email.ilike(search_term),
                User.username.ilike(search_term),
                User.display_name.ilike(search_term),
            )
        )

    # 筛选
    if role:
        query = query.where(User.role == role)
        count_query = count_query.where(User.role == role)

    if status:
        query = query.where(User.status == status)
        count_query = count_query.where(User.status == status)

    # 排序
    query = query.order_by(User.created_at.desc())

    # 分页
    offset = (pagination.page - 1) * pagination.page_size
    query = query.offset(offset).limit(pagination.page_size)

    # 执行
    result = await db.execute(query)
    users = result.scalars().all()

    count_result = await db.execute(count_query)
    total = count_result.scalar()

    items = [user_to_list_item(u) for u in users]
    paginated = PaginatedResponse.create(items, total, pagination)

    return ApiResponse(data=paginated, meta=create_meta(request))


# ============================================
# 获取单个用户
# ============================================

@router.get("/{user_id}", response_model=ApiResponse[UserResponse])
async def get_user(
    request: Request,
    user_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """获取用户详情"""
    # 权限检查：只能查看自己或有 user:read 权限
    if user_id != current_user.id:
        user_perms = get_role_permissions(current_user.role.value)
        if not has_permission(user_perms, "user:read"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied: user:read",
            )

    result = await db.execute(
        select(User).where(User.id == user_id, User.tenant_id == current_tenant.id, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    user_response = UserResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        role=user.role.value,
        status=user.status.value,
        tenant_id=user.tenant_id,
        last_login_at=user.last_login_at,
        email_verified_at=user.email_verified_at,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )

    return ApiResponse(data=user_response, meta=create_meta(request))


# ============================================
# 创建用户 (管理员)
# ============================================

@router.post("", response_model=ApiResponse[UserResponse], status_code=status.HTTP_201_CREATED)
async def create_user(
    request: Request,
    user_data: UserCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """创建用户 (需要 user:create 权限)"""
    user_perms = get_role_permissions(current_user.role.value)
    if not has_permission(user_perms, "user:create"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: user:create",
        )

    # 检查邮箱唯一性
    result = await db.execute(
        select(User).where(User.email == user_data.email, User.tenant_id == current_tenant.id, User.deleted_at.is_(None))
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered in this tenant",
        )

    # 检查用户名唯一性
    result = await db.execute(
        select(User).where(User.username == user_data.username, User.tenant_id == current_tenant.id, User.deleted_at.is_(None))
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already taken in this tenant",
        )

    # 验证角色权限：不能创建比自己权限更高的用户
    role_hierarchy = {"SUPER_ADMIN": 4, "ADMIN": 3, "MEMBER": 2, "VIEWER": 1}
    if role_hierarchy.get(user_data.role, 0) > role_hierarchy.get(current_user.role.value, 0):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot create user with higher role than yourself",
        )

    # 创建用户
    from app.core.security import hash_password
    user = User(
        tenant_id=current_tenant.id,
        email=user_data.email,
        username=user_data.username,
        password_hash=hash_password(user_data.password),
        display_name=user_data.display_name,
        role=user_data.role,
        status="ACTIVE",
        email_verified_at=datetime.now(timezone.utc),
    )
    db.add(user)
    await db.flush()

    await record_audit(
        db,
        tenant_id=current_tenant.id,
        user_id=current_user.id,
        action=AuditAction.CREATE,
        resource="user",
        resource_id=user.id,
        new_value={"email": user.email, "username": user.username, "role": _jsonable(user.role), "status": _jsonable(user.status)},
        request=request,
    )

    await db.commit()
    await db.refresh(user)

    user_response = UserResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        role=user.role.value,
        status=user.status.value,
        tenant_id=user.tenant_id,
        last_login_at=user.last_login_at,
        email_verified_at=user.email_verified_at,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )

    return ApiResponse(data=user_response, meta=create_meta(request))


# ============================================
# 更新用户
# ============================================

@router.patch("/{user_id}", response_model=ApiResponse[UserResponse])
async def update_user(
    request: Request,
    user_id: UUID,
    user_data: UserUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """更新用户信息"""
    # 权限检查
    user_perms = get_role_permissions(current_user.role.value)
    is_self = user_id == current_user.id

    if not is_self and not has_permission(user_perms, "user:update"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: user:update",
        )

    # 不能修改别人的角色/状态 (除非是管理员)
    if not is_self:
        if user_data.role is not None and not has_permission(user_perms, "user:update"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot change other user's role",
            )
        if user_data.status is not None and not has_permission(user_perms, "user:update"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot change other user's status",
            )

    result = await db.execute(
        select(User).where(User.id == user_id, User.tenant_id == current_tenant.id, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # 更新字段
    update_data = user_data.model_dump(exclude_unset=True)

    # 角色变更检查
    if "role" in update_data:
        role_hierarchy = {"SUPER_ADMIN": 4, "ADMIN": 3, "MEMBER": 2, "VIEWER": 1}
        if role_hierarchy.get(update_data["role"], 0) > role_hierarchy.get(current_user.role.value, 0):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot assign role higher than your own",
            )

    old_value = {field: _jsonable(getattr(user, field, None)) for field in update_data}

    for field, value in update_data.items():
        setattr(user, field, value)

    await record_audit(
        db,
        tenant_id=current_tenant.id,
        user_id=current_user.id,
        action=AuditAction.UPDATE,
        resource="user",
        resource_id=user.id,
        old_value=old_value,
        new_value={field: _jsonable(value) for field, value in update_data.items()},
        request=request,
    )

    await db.commit()
    await db.refresh(user)

    user_response = UserResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        role=user.role.value,
        status=user.status.value,
        tenant_id=user.tenant_id,
        last_login_at=user.last_login_at,
        email_verified_at=user.email_verified_at,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )

    return ApiResponse(data=user_response, meta=create_meta(request))


# ============================================
# 删除用户 (软删除)
# ============================================

@router.delete("/{user_id}", response_model=ApiResponse)
async def delete_user(
    request: Request,
    user_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """删除用户 (软删除，需要 user:delete 权限)"""
    user_perms = get_role_permissions(current_user.role.value)
    if not has_permission(user_perms, "user:delete"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: user:delete",
        )

    # 不能删除自己
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete yourself",
        )

    result = await db.execute(
        select(User).where(User.id == user_id, User.tenant_id == current_tenant.id, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # 软删除
    user.deleted_at = datetime.now(timezone.utc)
    user.status = "INACTIVE"

    # 撤销所有刷新 Token
    from app.models import RefreshToken
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked_at.is_(None),
        )
    )
    for token in result.scalars().all():
        token.revoked_at = datetime.now(timezone.utc)

    await record_audit(
        db,
        tenant_id=current_tenant.id,
        user_id=current_user.id,
        action=AuditAction.DELETE,
        resource="user",
        resource_id=user.id,
        old_value={"email": user.email, "username": user.username, "role": _jsonable(user.role)},
        request=request,
    )

    await db.commit()

    return ApiResponse(data={"message": "User deleted successfully"}, meta=create_meta(request))


# ============================================
# 获取当前用户权限
# ============================================

@router.get("/me/permissions", response_model=ApiResponse[list[str]])
async def get_my_permissions(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """获取当前用户的所有权限"""
    permissions = get_role_permissions(current_user.role.value)
    return ApiResponse(data=permissions, meta=create_meta(request))


# 导入缺失的模块