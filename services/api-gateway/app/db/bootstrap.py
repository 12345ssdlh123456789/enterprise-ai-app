"""首次启动时写入演示数据。

目标是「克隆下来就能登录看到东西」：一个演示租户、一个管理员、
两个可用模型（Ollama 对话 + 嵌入）。重复启动是幂等的。
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password
from app.models import (
    Model,
    ModelCapability,
    ModelProvider,
    Tenant,
    TenantPlan,
    TokenBudget,
    User,
    UserRole,
    UserStatus,
)

logger = logging.getLogger(__name__)


async def _get_or_create_tenant(session: AsyncSession) -> Tenant:
    result = await session.execute(select(Tenant).where(Tenant.slug == "demo"))
    tenant = result.scalar_one_or_none()
    if tenant:
        return tenant

    tenant = Tenant(
        id=uuid.uuid4(),
        name="Acme 企业",
        slug="demo",
        plan=TenantPlan.ENTERPRISE,
        settings={
            "default_model": settings.OLLAMA_CHAT_MODEL,
            "max_tokens_per_request": 8192,
            "retention_days": 90,
            "features": {
                "rag_enabled": True,
                "workflows_enabled": True,
                "analytics_enabled": True,
            },
        },
    )
    session.add(tenant)
    await session.flush()
    logger.info("Seeded demo tenant 'Acme 企业'")
    return tenant


async def _get_or_create_admin(session: AsyncSession, tenant: Tenant) -> User:
    email = settings.BOOTSTRAP_ADMIN_EMAIL
    result = await session.execute(
        select(User).where(User.email == email, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()
    if user:
        return user

    user = User(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        email=email,
        username="admin",
        password_hash=hash_password(settings.BOOTSTRAP_ADMIN_PASSWORD),
        display_name="管理员",
        role=UserRole.SUPER_ADMIN,
        status=UserStatus.ACTIVE,
        email_verified_at=datetime.now(timezone.utc),
    )
    session.add(user)
    await session.flush()
    logger.info("Seeded demo admin %s", email)
    return user


async def _get_or_create_model(
    session: AsyncSession,
    *,
    model_id: str,
    name: str,
    provider: ModelProvider,
    capabilities: list,
    context_window: int = 32768,
    max_output_tokens: int = 4096,
) -> None:
    result = await session.execute(select(Model).where(Model.id == model_id))
    if result.scalar_one_or_none():
        return

    session.add(
        Model(
            id=model_id,
            name=name,
            provider=provider,
            capabilities=capabilities,
            context_window=context_window,
            max_output_tokens=max_output_tokens,
            pricing={"input_token_price": 0.0, "output_token_price": 0.0, "currency": "USD"},
            parameters={"temperature": {"default": 0.7}, "max_tokens": {"default": 2048}},
            enabled=True,
        )
    )
    logger.info("Seeded model %s", model_id)


async def _get_or_create_budget(session: AsyncSession, tenant: Tenant) -> None:
    result = await session.execute(
        select(TokenBudget).where(TokenBudget.tenant_id == tenant.id, TokenBudget.period == "monthly")
    )
    if result.scalar_one_or_none():
        return
    now = datetime.now(timezone.utc)
    session.add(
        TokenBudget(
            tenant_id=tenant.id,
            period="monthly",
            limit=1_000_000,
            used=0,
            reset_at=now.replace(month=(now.month % 12) + 1, day=1),
        )
    )


async def bootstrap_demo_data(session: AsyncSession) -> None:
    """幂等地写入演示租户、管理员、模型与预算。"""
    tenant = await _get_or_create_tenant(session)
    await _get_or_create_admin(session, tenant)

    await _get_or_create_model(
        session,
        model_id=settings.OLLAMA_CHAT_MODEL,
        name=f"{settings.OLLAMA_CHAT_MODEL} (本地)",
        provider=ModelProvider.OLLAMA,
        capabilities=[ModelCapability.CHAT, ModelCapability.FUNCTION_CALLING],
        context_window=32768,
        max_output_tokens=4096,
    )
    await _get_or_create_model(
        session,
        model_id=settings.OLLAMA_EMBEDDING_MODEL,
        name=f"{settings.OLLAMA_EMBEDDING_MODEL} (本地嵌入)",
        provider=ModelProvider.OLLAMA,
        capabilities=[ModelCapability.EMBEDDING],
        context_window=2048,
        max_output_tokens=0,
    )
    await _get_or_create_budget(session, tenant)
