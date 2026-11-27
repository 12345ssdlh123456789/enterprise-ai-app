from datetime import datetime
from typing import Optional, Any, List
from uuid import UUID

from pydantic import AliasChoices, BaseModel, Field, ConfigDict


# Provider Schemas
class ProviderConfigBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    provider_type: str = Field(..., pattern="^(openai|anthropic|azure_openai|ollama)$")
    api_base: Optional[str] = None
    api_version: Optional[str] = None
    priority: int = Field(default=0, ge=0)
    rate_limit_rpm: int = Field(default=60, gt=0)
    rate_limit_tpm: int = Field(default=100000, gt=0)
    timeout_seconds: float = Field(default=60.0, gt=0)
    max_retries: int = Field(default=3, ge=0)
    meta: dict = Field(
        default_factory=dict,
        validation_alias=AliasChoices("meta", "metadata"),
        serialization_alias="metadata",
    )


class ProviderConfigCreate(ProviderConfigBase):
    api_key: str = Field(..., min_length=1)


class ProviderConfigUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    api_base: Optional[str] = None
    api_version: Optional[str] = None
    priority: Optional[int] = Field(None, ge=0)
    rate_limit_rpm: Optional[int] = Field(None, gt=0)
    rate_limit_tpm: Optional[int] = Field(None, gt=0)
    timeout_seconds: Optional[float] = Field(None, gt=0)
    max_retries: Optional[int] = Field(None, ge=0)
    meta: Optional[dict] = Field(
        None, validation_alias=AliasChoices("meta", "metadata"), serialization_alias="metadata"
    )
    status: Optional[str] = Field(None, pattern="^(active|degraded|unavailable)$")


class ProviderConfigRead(ProviderConfigBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    status: str
    created_at: datetime
    updated_at: datetime


# Model Schemas
class ModelConfigBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    display_name: str = Field(..., min_length=1, max_length=100)
    model_type: str = Field(..., pattern="^(chat|embedding|rerank)$")
    context_window: int = Field(default=4096, gt=0)
    max_output_tokens: int = Field(default=4096, gt=0)
    supports_streaming: bool = True
    supports_functions: bool = False
    supports_vision: bool = False
    input_cost_per_1k: int = Field(default=0, ge=0)  # micro-USD
    output_cost_per_1k: int = Field(default=0, ge=0)
    is_default: bool = False
    is_active: bool = True
    meta: dict = Field(
        default_factory=dict,
        validation_alias=AliasChoices("meta", "metadata"),
        serialization_alias="metadata",
    )


class ModelConfigCreate(ModelConfigBase):
    provider_id: UUID


class ModelConfigUpdate(BaseModel):
    display_name: Optional[str] = Field(None, min_length=1, max_length=100)
    context_window: Optional[int] = Field(None, gt=0)
    max_output_tokens: Optional[int] = Field(None, gt=0)
    supports_streaming: Optional[bool] = None
    supports_functions: Optional[bool] = None
    supports_vision: Optional[bool] = None
    input_cost_per_1k: Optional[int] = Field(None, ge=0)
    output_cost_per_1k: Optional[int] = Field(None, ge=0)
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None
    meta: Optional[dict] = Field(
        None, validation_alias=AliasChoices("meta", "metadata"), serialization_alias="metadata"
    )


class ModelConfigRead(ModelConfigBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    provider_id: UUID
    tenant_id: UUID
    created_at: datetime
    updated_at: datetime


# Chat Completion Schemas (OpenAI compatible)
class ChatMessage(BaseModel):
    role: str = Field(..., pattern="^(system|user|assistant|tool)$")
    content: Optional[str] = None
    name: Optional[str] = None
    tool_calls: Optional[List[dict]] = None
    tool_call_id: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    temperature: Optional[float] = Field(default=1.0, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(default=1.0, ge=0.0, le=1.0)
    n: Optional[int] = Field(default=1, ge=1, le=10)
    stream: Optional[bool] = False
    max_tokens: Optional[int] = Field(None, gt=0)
    presence_penalty: Optional[float] = Field(default=0.0, ge=-2.0, le=2.0)
    frequency_penalty: Optional[float] = Field(default=0.0, ge=-2.0, le=2.0)
    user: Optional[str] = None
    tools: Optional[List[dict]] = None
    tool_choice: Optional[Any] = None
    response_format: Optional[dict] = None


class ChatCompletionChoice(BaseModel):
    index: int
    message: ChatMessage
    finish_reason: Optional[str] = None


class ChatCompletionUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[ChatCompletionChoice]
    usage: ChatCompletionUsage
    system_fingerprint: Optional[str] = None


class ChatCompletionChunkChoice(BaseModel):
    index: int
    delta: ChatMessage
    finish_reason: Optional[str] = None


class ChatCompletionChunk(BaseModel):
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: List[ChatCompletionChunkChoice]
    system_fingerprint: Optional[str] = None


# Embedding Schemas
class EmbeddingRequest(BaseModel):
    model: str
    input: List[str] = Field(..., min_length=1)
    encoding_format: Optional[str] = Field(default="float", pattern="^(float|base64)$")
    dimensions: Optional[int] = Field(None, gt=0)
    user: Optional[str] = None


class EmbeddingData(BaseModel):
    object: str = "embedding"
    index: int
    embedding: List[float]


class EmbeddingResponse(BaseModel):
    object: str = "list"
    data: List[EmbeddingData]
    model: str
    usage: dict


# Usage/Cost Schemas
class UsageRecordRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    user_id: Optional[UUID]
    provider_id: UUID
    model_id: UUID
    request_id: str
    model_type: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: int
    latency_ms: int
    status: str
    error_message: Optional[str]
    meta: dict = Field(validation_alias=AliasChoices("meta", "metadata"), serialization_alias="metadata")
    created_at: datetime


class CostSummary(BaseModel):
    total_tokens: int
    total_cost_usd: float
    by_model: dict
    by_provider: dict
    # 未传日期筛选时服务返回 None，这里保持同为可选字符串（服务原样回传入参）。
    period_start: Optional[str] = None
    period_end: Optional[str] = None