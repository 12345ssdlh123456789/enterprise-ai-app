# API Gateway - Core Security & Authentication

import hashlib
import secrets
import time
from datetime import datetime, timezone
from typing import Optional, List, Dict
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_async_db
from app.models import User, APIKey, Tenant


# ============================================
# 密码哈希
# ============================================

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=settings.BCRYPT_ROUNDS)


def hash_password(password: str) -> str:
    """哈希密码"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return pwd_context.verify(plain_password, hashed_password)


def hash_token(token: str) -> str:
    """对 Token 做确定性哈希。

    bcrypt 每次加盐，结果无法用于按列查询，所以刷新 Token 用 SHA-256 存储。
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ============================================
# JWT Token 处理
# ============================================

class TokenPayload(BaseModel):
    """JWT 载荷"""
    sub: str  # user_id
    email: str
    role: str
    tenant_id: str
    permissions: List[str] = []
    type: str  # "access" or "refresh"
    iat: int
    exp: int


def create_access_token(user: User, tenant: Tenant) -> str:
    """创建访问 Token"""
    now = int(time.time())
    expire = now + settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60

    # 获取权限
    permissions = get_role_permissions(user.role)

    payload = TokenPayload(
        sub=str(user.id),
        email=user.email,
        role=user.role.value,
        tenant_id=str(tenant.id),
        permissions=permissions,
        type="access",
        iat=now,
        exp=expire,
    )

    return jwt.encode(payload.model_dump(), settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(user: User, tenant: Tenant) -> str:
    """创建刷新 Token"""
    now = int(time.time())
    expire = now + settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60

    payload = TokenPayload(
        sub=str(user.id),
        email=user.email,
        role=user.role.value,
        tenant_id=str(tenant.id),
        permissions=[],
        type="refresh",
        iat=now,
        exp=expire,
    )

    return jwt.encode(payload.model_dump(), settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> TokenPayload:
    """解码并验证 Token"""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return TokenPayload(**payload)
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ============================================
# 权限映射
# ============================================

ROLE_PERMISSIONS: Dict[str, List[str]] = {
    "SUPER_ADMIN": ["*:*"],
    "ADMIN": [
        "tenant:read", "tenant:update",
        "user:create", "user:read", "user:update", "user:delete",
        "knowledge-base:create", "knowledge-base:read", "knowledge-base:update", "knowledge-base:delete",
        "document:create", "document:read", "document:update", "document:delete",
        "workflow:create", "workflow:read", "workflow:update", "workflow:delete", "workflow:execute",
        "chat:create", "chat:read", "chat:update", "chat:delete",
        "audit:read",
        "analytics:read",
    ],
    "MEMBER": [
        "knowledge-base:read",
        "document:create", "document:read", "document:update",
        "workflow:create", "workflow:read", "workflow:update", "workflow:execute",
        "chat:create", "chat:read",
    ],
    "VIEWER": [
        "knowledge-base:read",
        "document:read",
        "chat:create", "chat:read",
    ],
}


def get_role_permissions(role: str) -> List[str]:
    """获取角色权限"""
    return ROLE_PERMISSIONS.get(role, [])


def has_permission(user_permissions: List[str], required: str) -> bool:
    """检查权限 (支持通配符)"""
    if "*:*" in user_permissions:
        return True
    if required in user_permissions:
        return True
    # 检查通配符权限
    resource, action = required.split(":")
    if f"{resource}:*" in user_permissions:
        return True
    return False


# ============================================
# 依赖注入：获取当前用户
# ============================================

security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_async_db),
) -> User:
    """获取当前认证用户"""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_data = decode_token(credentials.credentials)

    if token_data.type != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 查询用户
    result = await db.execute(
        select(User).where(User.id == UUID(token_data.sub), User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user.status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is not active",
        )

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """获取当前激活用户"""
    if current_user.status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        )
    return current_user


async def get_current_tenant(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_async_db),
) -> Tenant:
    """获取当前用户的租户"""
    result = await db.execute(
        select(Tenant).where(Tenant.id == current_user.tenant_id)
    )
    tenant = result.scalar_one_or_none()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )

    return tenant


# ============================================
# 权限检查依赖
# ============================================

class RequirePermissions:
    """权限检查依赖"""

    def __init__(self, *permissions: str):
        self.permissions = permissions

    def __call__(self, current_user: User = Depends(get_current_user)) -> User:
        user_perms = get_role_permissions(current_user.role.value)

        for perm in self.permissions:
            if not has_permission(user_perms, perm):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Permission denied: {perm}",
                )

        return current_user


# 常用权限依赖
require_admin = RequirePermissions("user:create")
require_super_admin = RequirePermissions("*:*")
require_kb_write = RequirePermissions("knowledge-base:create")
require_doc_write = RequirePermissions("document:create")
require_workflow_execute = RequirePermissions("workflow:execute")


# ============================================
# API Key 认证 (服务间调用)
# ============================================

api_key_security = HTTPBearer(auto_error=False, scheme_name="API Key")


async def verify_api_key(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(api_key_security),
    db: AsyncSession = Depends(get_async_db),
) -> APIKey:
    """验证 API Key (用于服务间调用)"""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 计算 key hash
    key_hash = hashlib.sha256(credentials.credentials.encode()).hexdigest()
    key_prefix = credentials.credentials[:20]

    result = await db.execute(
        select(APIKey).where(
            APIKey.key_hash == key_hash,
            APIKey.key_prefix == key_prefix,
            APIKey.revoked_at.is_(None),
        )
    )
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key",
        )

    if api_key.expires_at and api_key.expires_at < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key expired",
        )

    # 更新最后使用时间
    api_key.last_used_at = datetime.now(timezone.utc)
    await db.commit()

    return api_key


def generate_api_key() -> tuple[str, str, str]:
    """生成 API Key
    Returns: (full_key, key_hash, key_prefix)
    """
    raw = secrets.token_urlsafe(32)
    full_key = f"eak_{raw}"  # enterprise-ai-key
    key_hash = hashlib.sha256(full_key.encode()).hexdigest()
    key_prefix = full_key[:20]
    return full_key, key_hash, key_prefix


# ============================================
# 服务间调用 Token
# ============================================

def create_service_token() -> str:
    """创建服务间调用 Token"""
    now = int(time.time())
    expire = now + 3600  # 1 小时

    payload = {
        "sub": "service",
        "type": "service",
        "iat": now,
        "exp": expire,
    }

    return jwt.encode(payload, settings.SERVICE_API_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_service_token(token: str) -> bool:
    """验证服务间调用 Token"""
    try:
        payload = jwt.decode(token, settings.SERVICE_API_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload.get("type") == "service"
    except JWTError:
        return False