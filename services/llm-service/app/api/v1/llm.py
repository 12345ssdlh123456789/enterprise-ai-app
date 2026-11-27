from uuid import UUID
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_session
from app.schemas import (
    ProviderConfigCreate,
    ProviderConfigUpdate,
    ProviderConfigRead,
    ModelConfigCreate,
    ModelConfigUpdate,
    ModelConfigRead,
    ChatCompletionRequest,
    ChatCompletionResponse,
    EmbeddingRequest,
    EmbeddingResponse,
    UsageRecordRead,
    CostSummary,
)
from app.models import ProviderConfig, ModelConfig, UsageRecord
from app.services.llm_service import llm_service
from app.services.providers import ProviderFactory
from app.core.context import current_tenant_id, current_user_id

router = APIRouter(prefix="/providers", tags=["Providers"])
model_router = APIRouter(prefix="/models", tags=["Models"])
chat_router = APIRouter(prefix="/chat", tags=["Chat"])
embedding_router = APIRouter(prefix="/embeddings", tags=["Embeddings"])
usage_router = APIRouter(prefix="/usage", tags=["Usage"])


# Provider CRUD
@router.post("", response_model=ProviderConfigRead, status_code=status.HTTP_201_CREATED)
async def create_provider(
    provider_in: ProviderConfigCreate,
    session: AsyncSession = Depends(get_session),
):
    tenant_id = current_tenant_id()

    # Check name uniqueness
    stmt = select(ProviderConfig).where(
        ProviderConfig.tenant_id == tenant_id,
        ProviderConfig.name == provider_in.name,
    )
    result = await session.execute(stmt)
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Provider name already exists")

    provider = ProviderConfig(
        tenant_id=tenant_id,
        **provider_in.model_dump(),
    )
    session.add(provider)
    await session.commit()
    await session.refresh(provider)
    return provider


@router.get("", response_model=List[ProviderConfigRead])
async def list_providers(
    session: AsyncSession = Depends(get_session),
    skip: int = 0,
    limit: int = 50,
):
    tenant_id = current_tenant_id()
    stmt = select(ProviderConfig).where(ProviderConfig.tenant_id == tenant_id).offset(skip).limit(limit)
    result = await session.execute(stmt)
    return result.scalars().all()


@router.get("/{provider_id}", response_model=ProviderConfigRead)
async def get_provider(provider_id: UUID, session: AsyncSession = Depends(get_session)):
    provider = await session.get(ProviderConfig, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    return provider


@router.patch("/{provider_id}", response_model=ProviderConfigRead)
async def update_provider(
    provider_id: UUID,
    provider_in: ProviderConfigUpdate,
    session: AsyncSession = Depends(get_session),
):
    provider = await session.get(ProviderConfig, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    for field, value in provider_in.model_dump(exclude_unset=True).items():
        setattr(provider, field, value)
    await session.commit()
    await session.refresh(provider)
    return provider


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(provider_id: UUID, session: AsyncSession = Depends(get_session)):
    provider = await session.get(ProviderConfig, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    await session.delete(provider)
    await session.commit()


# Model CRUD
@model_router.post("", response_model=ModelConfigRead, status_code=status.HTTP_201_CREATED)
async def create_model(
    model_in: ModelConfigCreate,
    session: AsyncSession = Depends(get_session),
):
    tenant_id = current_tenant_id()

    # Verify provider exists
    provider = await session.get(ProviderConfig, model_in.provider_id)
    if not provider or provider.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Provider not found")

    # Check uniqueness
    stmt = select(ModelConfig).where(
        ModelConfig.provider_id == model_in.provider_id,
        ModelConfig.name == model_in.name,
    )
    result = await session.execute(stmt)
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Model already exists for this provider")

    # If is_default, unset other defaults for same type
    if model_in.is_default:
        stmt = select(ModelConfig).where(
            ModelConfig.tenant_id == tenant_id,
            ModelConfig.model_type == model_in.model_type,
            ModelConfig.is_default == True,
        )
        result = await session.execute(stmt)
        for m in result.scalars().all():
            m.is_default = False

    model = ModelConfig(
        tenant_id=tenant_id,
        **model_in.model_dump(),
    )
    session.add(model)
    await session.commit()
    await session.refresh(model)

    # Reinitialize LLM service
    llm_service._initialized = False

    return model


@model_router.get("", response_model=List[ModelConfigRead])
async def list_models(
    session: AsyncSession = Depends(get_session),
    provider_id: Optional[UUID] = None,
    model_type: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
):
    tenant_id = current_tenant_id()
    stmt = select(ModelConfig).where(ModelConfig.tenant_id == tenant_id)

    if provider_id:
        stmt = stmt.where(ModelConfig.provider_id == provider_id)
    if model_type:
        stmt = stmt.where(ModelConfig.model_type == model_type)

    stmt = stmt.offset(skip).limit(limit)
    result = await session.execute(stmt)
    return result.scalars().all()


@model_router.get("/{model_id}", response_model=ModelConfigRead)
async def get_model(model_id: UUID, session: AsyncSession = Depends(get_session)):
    model = await session.get(ModelConfig, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    return model


@model_router.patch("/{model_id}", response_model=ModelConfigRead)
async def update_model(
    model_id: UUID,
    model_in: ModelConfigUpdate,
    session: AsyncSession = Depends(get_session),
):
    model = await session.get(ModelConfig, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    # Handle is_default
    if model_in.is_default is True:
        tenant_id = current_tenant_id()
        stmt = select(ModelConfig).where(
            ModelConfig.tenant_id == tenant_id,
            ModelConfig.model_type == model.model_type,
            ModelConfig.is_default == True,
        )
        result = await session.execute(stmt)
        for m in result.scalars().all():
            m.is_default = False

    for field, value in model_in.model_dump(exclude_unset=True).items():
        setattr(model, field, value)
    await session.commit()
    await session.refresh(model)

    llm_service._initialized = False

    return model


@model_router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(model_id: UUID, session: AsyncSession = Depends(get_session)):
    model = await session.get(ModelConfig, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    await session.delete(model)
    await session.commit()

    llm_service._initialized = False


# OpenAI-compatible model listing
@model_router.get("/openai/list")
async def list_openai_models():
    """OpenAI-compatible model listing endpoint."""
    tenant_id = current_tenant_id()
    models = await llm_service.get_models(str(tenant_id))
    return {"object": "list", "data": models}


# Chat Completions
@chat_router.post("/completions", response_model=ChatCompletionResponse)
async def create_chat_completion(
    request: ChatCompletionRequest,
    http_request: Request,
):
    tenant_id = current_tenant_id()
    user_id = str(current_user_id())

    try:
        if request.stream:
            return StreamingResponse(
                llm_service.stream_chat_completion(str(tenant_id), user_id, request.model_dump(exclude_unset=True)),
                media_type="text/event-stream",
            )
        else:
            result = await llm_service.chat_completion(str(tenant_id), user_id, request.model_dump(exclude_unset=True))
            return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Embeddings
@embedding_router.post("", response_model=EmbeddingResponse)
async def create_embeddings(
    request: EmbeddingRequest,
    http_request: Request,
):
    tenant_id = current_tenant_id()
    user_id = str(current_user_id())

    try:
        result = await llm_service.embeddings(str(tenant_id), user_id, request.model_dump(exclude_unset=True))
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Usage & Cost
@usage_router.get("/records", response_model=List[UsageRecordRead])
async def list_usage_records(
    session: AsyncSession = Depends(get_session),
    user_id: Optional[UUID] = None,
    model_id: Optional[UUID] = None,
    provider_id: Optional[UUID] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    skip: int = 0,
    limit: int = 100,
):
    tenant_id = current_tenant_id()
    stmt = select(UsageRecord).where(UsageRecord.tenant_id == tenant_id)

    if user_id:
        stmt = stmt.where(UsageRecord.user_id == user_id)
    if model_id:
        stmt = stmt.where(UsageRecord.model_id == model_id)
    if provider_id:
        stmt = stmt.where(UsageRecord.provider_id == provider_id)
    if start_date:
        stmt = stmt.where(UsageRecord.created_at >= start_date)
    if end_date:
        stmt = stmt.where(UsageRecord.created_at <= end_date)

    stmt = stmt.order_by(UsageRecord.created_at.desc()).offset(skip).limit(limit)
    result = await session.execute(stmt)
    return result.scalars().all()


@usage_router.get("/cost-summary", response_model=CostSummary)
async def get_cost_summary(
    user_id: Optional[UUID] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
):
    tenant_id = current_tenant_id()
    summary = await llm_service.get_cost_summary(
        str(tenant_id),
        str(user_id) if user_id else None,
        start_date,
        end_date,
    )
    return summary


# Health check for providers
@router.get("/{provider_id}/health")
async def provider_health(provider_id: UUID, session: AsyncSession = Depends(get_session)):
    provider = await session.get(ProviderConfig, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    # Try to create a test client
    try:
        # Get a default model for this provider
        stmt = select(ModelConfig).where(
            ModelConfig.provider_id == provider_id,
            ModelConfig.is_active == True,
        ).limit(1)
        result = await session.execute(stmt)
        model = result.scalar_one_or_none()

        if model:
            provider_instance = ProviderFactory.create(provider, model)
            healthy = provider_instance.is_healthy()
        else:
            healthy = False

        return {
            "provider_id": str(provider_id),
            "status": provider.status.value,
            "healthy": healthy,
            "circuit_breaker": "closed" if healthy else "open",
        }
    except Exception as e:
        return {
            "provider_id": str(provider_id),
            "status": provider.status.value,
            "healthy": False,
            "error": str(e),
        }