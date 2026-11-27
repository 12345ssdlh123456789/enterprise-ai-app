# API Gateway - Auth Routes

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    hash_password,
    hash_token,
    verify_password,
)
from app.db.session import get_async_db
from app.models import AuditAction, User, Tenant, RefreshToken, UserRole, UserStatus, TenantPlan
from app.services.audit import record_audit
from app.schemas import (
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    RefreshTokenRequest,
    ChangePasswordRequest,
    ConfirmResetPasswordRequest,
    UserResponse,
    ApiResponse,
    ResponseMeta,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


# ============================================
# 辅助函数
# ============================================

def create_meta(request: Request) -> ResponseMeta:
    """创建响应元数据"""
    return ResponseMeta(
        request_id=request.state.request_id if hasattr(request.state, "request_id") else "unknown",
        timestamp=datetime.now(timezone.utc),
        version=settings.APP_VERSION,
    )


async def set_refresh_token_cookie(response: Response, refresh_token: str):
    """设置刷新 Token Cookie"""
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=settings.ENVIRONMENT == "production",
        samesite="lax",
        max_age=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path="/",
    )


def clear_refresh_token_cookie(response: Response):
    """清除刷新 Token Cookie"""
    response.delete_cookie(key="refresh_token", path="/", secure=settings.ENVIRONMENT == "production", samesite="lax")


# ============================================
# 登录
# ============================================

@router.post("/login", response_model=ApiResponse[TokenResponse])
async def login(
    request: Request,
    response: Response,
    login_data: LoginRequest,
    db: AsyncSession = Depends(get_async_db),
):
    """用户登录"""
    # 查询用户 (支持邮箱或用户名)
    result = await db.execute(
        select(User).where(
            (User.email == login_data.email) | (User.username == login_data.email),
            User.deleted_at.is_(None),
        )
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(login_data.password, user.password_hash):
        if user:
            # 已知账号的密码错误：留痕，便于发现暴力破解
            await record_audit(
                db,
                tenant_id=user.tenant_id,
                user_id=user.id,
                action=AuditAction.LOGIN,
                resource="auth",
                request=request,
                success=False,
                error_message="凭据无效（邮箱或密码错误）",
                commit=True,
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email/username or password",
        )

    if user.status != "ACTIVE":
        await record_audit(
            db,
            tenant_id=user.tenant_id,
            user_id=user.id,
            action=AuditAction.LOGIN,
            resource="auth",
            request=request,
            success=False,
            error_message=f"账号状态不可登录：{user.status.value}",
            commit=True,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is not active. Please contact administrator.",
        )

    # 获取租户
    result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = result.scalar_one_or_none()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Tenant not found",
        )

    # 创建 Token
    access_token = create_access_token(user, tenant)
    refresh_token = create_refresh_token(user, tenant)

    # 保存刷新 Token 到数据库
    token_hash = hash_token(refresh_token)  # 确定性哈希，便于按列查询
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)

    db_refresh_token = RefreshToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(db_refresh_token)

    # 更新最后登录时间
    user.last_login_at = datetime.now(timezone.utc)

    await record_audit(
        db,
        tenant_id=user.tenant_id,
        user_id=user.id,
        action=AuditAction.LOGIN,
        resource="auth",
        request=request,
        new_value={"method": "password", "remember_me": bool(login_data.remember_me)},
    )

    await db.commit()

    # 设置 Cookie (可选，用于浏览器客户端)
    if login_data.remember_me:
        await set_refresh_token_cookie(response, refresh_token)

    # 构建响应
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

    token_response = TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=user_response,
    )

    return ApiResponse(data=token_response, meta=create_meta(request))


# ============================================
# OAuth2 密码流登录 (兼容 Swagger UI)
# ============================================

@router.post("/login/oauth", response_model=TokenResponse, include_in_schema=False)
async def login_oauth(
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_async_db),
):
    """OAuth2 密码流登录 (用于 Swagger UI 测试)"""
    login_data = LoginRequest(email=form_data.username, password=form_data.password, remember_me=True)
    # 复用登录逻辑
    result = await db.execute(
        select(User).where(
            (User.email == login_data.email) | (User.username == login_data.email),
            User.deleted_at.is_(None),
        )
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(login_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email/username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = result.scalar_one_or_none()

    access_token = create_access_token(user, tenant)
    refresh_token = create_refresh_token(user, tenant)

    token_hash = hash_token(refresh_token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)

    db_refresh_token = RefreshToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(db_refresh_token)

    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()

    await set_refresh_token_cookie(response, refresh_token)

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

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=user_response,
    )


# ============================================
# 注册
# ============================================

@router.post("/register", response_model=ApiResponse[TokenResponse], status_code=status.HTTP_201_CREATED)
async def register(
    request: Request,
    response: Response,
    register_data: RegisterRequest,
    db: AsyncSession = Depends(get_async_db),
):
    """用户注册 (创建租户 + 管理员用户)"""
    # 检查邮箱是否已存在
    result = await db.execute(
        select(User).where(User.email == register_data.email, User.deleted_at.is_(None))
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # 检查用户名是否已存在
    result = await db.execute(
        select(User).where(User.username == register_data.username, User.deleted_at.is_(None))
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already taken",
        )

    # 确定租户
    tenant = None
    if register_data.tenant_slug:
        # 加入现有租户
        result = await db.execute(select(Tenant).where(Tenant.slug == register_data.tenant_slug))
        tenant = result.scalar_one_or_none()
        if not tenant:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tenant not found",
            )
        # 检查租户是否允许公开注册
        if not tenant.settings.get("allowPublicSignup", False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This tenant does not allow public signup",
            )
    else:
        # 创建新租户
        slug = register_data.username.lower().replace("_", "-")
        # 确保 slug 唯一
        counter = 1
        base_slug = slug
        while True:
            result = await db.execute(select(Tenant).where(Tenant.slug == slug))
            if not result.scalar_one_or_none():
                break
            slug = f"{base_slug}-{counter}"
            counter += 1

        tenant = Tenant(
            name=f"{register_data.display_name or register_data.username}'s Workspace",
            slug=slug,
            plan=TenantPlan.FREE,
            settings={
                "allowPublicSignup": True,
                "defaultUserRole": "MEMBER",
                "ssoEnabled": False,
                "dataRetentionDays": 365,
                "maxKnowledgeBases": 10,
                "maxDocumentsPerKB": 1000,
                "maxTokenBudgetMonthly": 1000000,
            },
        )
        db.add(tenant)
        await db.flush()  # 获取 tenant.id

    # 创建用户
    user = User(
        tenant_id=tenant.id,
        email=register_data.email,
        username=register_data.username,
        password_hash=hash_password(register_data.password),
        display_name=register_data.display_name,
        role=UserRole.ADMIN if not register_data.tenant_slug else UserRole.MEMBER,
        status=UserStatus.ACTIVE,
        email_verified_at=datetime.now(timezone.utc),  # 开发环境自动验证
    )
    db.add(user)
    await db.flush()

    # 创建 Token
    access_token = create_access_token(user, tenant)
    refresh_token = create_refresh_token(user, tenant)

    token_hash = hash_token(refresh_token)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)

    db_refresh_token = RefreshToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(db_refresh_token)

    await db.commit()

    await set_refresh_token_cookie(response, refresh_token)

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

    token_response = TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=user_response,
    )

    return ApiResponse(data=token_response, meta=create_meta(request))


# ============================================
# 刷新 Token
# ============================================

@router.post("/refresh", response_model=ApiResponse[TokenResponse])
async def refresh_token(
    request: Request,
    response: Response,
    refresh_data: Optional[RefreshTokenRequest] = None,
    db: AsyncSession = Depends(get_async_db),
):
    """刷新访问 Token"""
    # 从请求体或 Cookie 获取刷新 Token
    refresh_token = None
    if refresh_data and refresh_data.refresh_token:
        refresh_token = refresh_data.refresh_token
    else:
        refresh_token = request.cookies.get("refresh_token")

    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token required",
        )

    # 解码并验证 Token
    try:
        token_data = decode_token(refresh_token)
    except HTTPException:
        raise

    if token_data.type != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )

    # 验证数据库中的刷新 Token
    token_hash = hash_token(refresh_token)
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == UUID(token_data.sub),
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > datetime.now(timezone.utc),
        )
    )
    db_refresh_token = result.scalar_one_or_none()

    if not db_refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token revoked or expired",
        )

    # 获取用户和租户
    result = await db.execute(
        select(User).where(User.id == UUID(token_data.sub), User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()

    if not user or user.status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = result.scalar_one_or_none()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Tenant not found",
        )

    # 撤销旧刷新 Token
    db_refresh_token.revoked_at = datetime.now(timezone.utc)

    # 创建新 Token
    new_access_token = create_access_token(user, tenant)
    new_refresh_token = create_refresh_token(user, tenant)

    # 保存新刷新 Token
    new_token_hash = hash_token(new_refresh_token)
    new_expires_at = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)

    new_db_refresh_token = RefreshToken(
        user_id=user.id,
        token_hash=new_token_hash,
        expires_at=new_expires_at,
    )
    db.add(new_db_refresh_token)

    await db.commit()

    await set_refresh_token_cookie(response, new_refresh_token)

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

    token_response = TokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=user_response,
    )

    return ApiResponse(data=token_response, meta=create_meta(request))


# ============================================
# 登出
# ============================================

@router.post("/logout", response_model=ApiResponse)
async def logout(
    request: Request,
    response: Response,
    refresh_data: Optional[RefreshTokenRequest] = None,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """用户登出 (撤销刷新 Token)"""
    refresh_token = None
    if refresh_data and refresh_data.refresh_token:
        refresh_token = refresh_data.refresh_token
    else:
        refresh_token = request.cookies.get("refresh_token")

    if refresh_token:
        token_hash = hash_token(refresh_token)
        result = await db.execute(
            select(RefreshToken).where(
                RefreshToken.user_id == current_user.id,
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked_at.is_(None),
            )
        )
        db_refresh_token = result.scalar_one_or_none()

        if db_refresh_token:
            db_refresh_token.revoked_at = datetime.now(timezone.utc)
            await db.commit()

    await record_audit(
        db,
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        action=AuditAction.LOGOUT,
        resource="auth",
        request=request,
        commit=True,
    )

    clear_refresh_token_cookie(response)

    return ApiResponse(data={"message": "Logged out successfully"}, meta=create_meta(request))


# ============================================
# 撤销所有会话
# ============================================

@router.post("/revoke-all-sessions", response_model=ApiResponse)
async def revoke_all_sessions(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """撤销用户所有会话 (修改密码、安全设置变更后调用)"""
    # 撤销所有刷新 Token
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == current_user.id,
            RefreshToken.revoked_at.is_(None),
        )
    )
    for token in result.scalars().all():
        token.revoked_at = datetime.now(timezone.utc)

    await db.commit()

    clear_refresh_token_cookie(response)

    return ApiResponse(data={"message": "All sessions revoked"}, meta=create_meta(request))


# ============================================
# 获取当前用户信息
# ============================================

@router.get("/me", response_model=ApiResponse[UserResponse])
async def get_current_user_info(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """获取当前认证用户信息"""
    user_response = UserResponse(
        id=current_user.id,
        email=current_user.email,
        username=current_user.username,
        display_name=current_user.display_name,
        avatar_url=current_user.avatar_url,
        role=current_user.role.value,
        status=current_user.status.value,
        tenant_id=current_user.tenant_id,
        last_login_at=current_user.last_login_at,
        email_verified_at=current_user.email_verified_at,
        created_at=current_user.created_at,
        updated_at=current_user.updated_at,
    )

    return ApiResponse(data=user_response, meta=create_meta(request))


# ============================================
# 修改密码
# ============================================

@router.post("/change-password", response_model=ApiResponse)
async def change_password(
    request: Request,
    response: Response,
    password_data: ChangePasswordRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """修改密码 (需要验证当前密码)"""
    if not verify_password(password_data.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    # 更新密码
    current_user.password_hash = hash_password(password_data.new_password)

    # 撤销所有现有会话 (安全最佳实践)
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == current_user.id,
            RefreshToken.revoked_at.is_(None),
        )
    )
    for token in result.scalars().all():
        token.revoked_at = datetime.now(timezone.utc)

    await db.commit()

    clear_refresh_token_cookie(response)

    return ApiResponse(data={"message": "Password changed successfully. Please login again."}, meta=create_meta(request))


# ============================================
# 请求重置密码 (发送邮件)
# ============================================

@router.post("/forgot-password", response_model=ApiResponse)
async def forgot_password(
    request: Request,
    email: EmailStr,
    db: AsyncSession = Depends(get_async_db),
):
    """请求重置密码 (发送重置邮件)"""
    # 始终返回成功，防止邮箱枚举
    result = await db.execute(
        select(User).where(User.email == email, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()

    if user:
        # TODO: 生成重置 Token，发送邮件
        # reset_token = create_password_reset_token(user)
        # await send_reset_email(user.email, reset_token)
        pass

    return ApiResponse(
        data={"message": "If the email exists, a password reset link has been sent"},
        meta=create_meta(request),
    )


# ============================================
# 确认重置密码
# ============================================

@router.post("/reset-password", response_model=ApiResponse)
async def reset_password(
    request: Request,
    response: Response,
    reset_data: ConfirmResetPasswordRequest,
    db: AsyncSession = Depends(get_async_db),
):
    """确认重置密码 (使用邮件中的 Token)"""
    # TODO: 验证重置 Token
    # token_data = decode_token(reset_data.token)
    # if token_data.type != "password_reset":
    #     raise HTTPException(...)
    pass

    # 暂时返回未实现
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Password reset not implemented yet",
    )


# 导入缺失的枚举