# API Gateway - Models Routes

from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import get_current_user, get_current_tenant, get_role_permissions, has_permission
from app.db.session import get_async_db
from app.models import AuditAction, Model, User, Tenant
from app.services.audit import record_audit
from app.schemas import (
    ModelSchema,
    ModelPricingSchema,
    ModelParametersSchema,
    ApiResponse,
    ResponseMeta,
)

router = APIRouter(prefix="/models", tags=["Models"])

def _has_capability(model: Model, capability: str) -> bool:
    """判断模型是否具备某项能力。

    capabilities 是 JSON 列，SQLite 下 JSONB.contains() 生成不了有效条件，
    所以统一在 Python 侧判断。
    """
    values = []
    for cap in model.capabilities or []:
        values.append(getattr(cap, "value", str(cap)))
    return capability.upper() in [str(v).upper() for v in values]


def create_meta(request: Request) -> ResponseMeta:
    return ResponseMeta(
        request_id=getattr(request.state, "request_id", "unknown"),
        timestamp=datetime.now(timezone.utc),
        version=settings.APP_VERSION,
    )


def _enum_value(value: object) -> str:
    return value.value if hasattr(value, 'value') else str(value)


def model_to_schema(m: Model) -> ModelSchema:
    return ModelSchema(
        id=m.id,
        name=m.name,
        provider=_enum_value(m.provider),
        capabilities=[_enum_value(c) for c in (m.capabilities or [])],
        context_window=m.context_window,
        max_output_tokens=m.max_output_tokens,
        pricing=ModelPricingSchema(**m.pricing),
        parameters=ModelParametersSchema(**m.parameters),
        enabled=m.enabled,
    )


# ============================================
# 获取模型列表
# ============================================

@router.get("", response_model=ApiResponse[List[ModelSchema]])
async def list_models(
    request: Request,
    provider: Optional[str] = Query(None, description="按提供商筛选"),
    capability: Optional[str] = Query(None, description="按能力筛选"),
    enabled_only: bool = Query(True, description="仅启用的模型"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """获取可用模型列表"""
    user_perms = get_role_permissions(current_user.role.value)
    if not has_permission(user_perms, "chat:create") and not has_permission(user_perms, "knowledge-base:create"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied",
        )

    query = select(Model)

    if enabled_only:
        query = query.where(Model.enabled == True)

    if provider:
        query = query.where(Model.provider == provider)

    if capability:
        # 数组包含查询
        query = query.where(Model.capabilities.contains([capability]))

    query = query.order_by(Model.provider, Model.name)

    result = await db.execute(query)
    models = result.scalars().all()

    return ApiResponse(data=[model_to_schema(m) for m in models], meta=create_meta(request))


# ============================================
# 获取单个模型
# ============================================

@router.get("/{model_id}", response_model=ApiResponse[ModelSchema])
async def get_model(
    request: Request,
    model_id: str,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """获取模型详情"""
    result = await db.execute(select(Model).where(Model.id == model_id))
    model = result.scalar_one_or_none()

    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model not found",
        )

    return ApiResponse(data=model_to_schema(model), meta=create_meta(request))


# ============================================
# 获取默认模型
# ============================================

@router.get("/defaults/chat", response_model=ApiResponse[ModelSchema])
async def get_default_chat_model(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """获取默认聊天模型"""
    result = await db.execute(select(Model).where(Model.enabled == True))
    enabled_models = list(result.scalars().all())

    model = next((m for m in enabled_models if m.id == settings.DEFAULT_CHAT_MODEL), None)
    if not model:
        # 回退到第一个启用的聊天模型
        model = next((m for m in enabled_models if _has_capability(m, "CHAT")), None)

    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No chat model available",
        )

    return ApiResponse(data=model_to_schema(model), meta=create_meta(request))


@router.get("/defaults/embedding", response_model=ApiResponse[ModelSchema])
async def get_default_embedding_model(
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """获取默认嵌入模型"""
    result = await db.execute(select(Model).where(Model.enabled == True))
    enabled_models = list(result.scalars().all())

    model = next((m for m in enabled_models if m.id == settings.DEFAULT_EMBEDDING_MODEL), None)
    if not model:
        model = next((m for m in enabled_models if _has_capability(m, "EMBEDDING")), None)

    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No embedding model available",
        )

    return ApiResponse(data=model_to_schema(model), meta=create_meta(request))


# ============================================
# 更新模型（管理后台：启用 / 停用）
# ============================================

from pydantic import BaseModel as _PydModel


class ModelUpdateRequest(_PydModel):
    enabled: Optional[bool] = None


@router.patch("/{model_id}", response_model=ApiResponse[ModelSchema])
async def update_model(
    request: Request,
    model_id: str,
    payload: ModelUpdateRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """更新模型配置。目前只开放 enabled 开关，且仅管理员可操作。"""
    if _enum_value(current_user.role) not in ("SUPER_ADMIN", "ADMIN"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有管理员可以修改模型配置",
        )

    result = await db.execute(select(Model).where(Model.id == model_id))
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Model not found")

    previous_enabled = model.enabled
    if payload.enabled is not None:
        model.enabled = payload.enabled

    await record_audit(
        db,
        tenant_id=current_tenant.id,
        user_id=current_user.id,
        action=AuditAction.UPDATE,
        resource="model",
        # 模型 ID 是 "provider:model" 形式的字符串，不是 UUID，放 new_value 里
        new_value={"model_id": model.id, "enabled": model.enabled, "previous_enabled": previous_enabled},
        request=request,
    )

    await db.commit()
    await db.refresh(model)

    return ApiResponse(data=model_to_schema(model), meta=create_meta(request))
