import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Uuid as UUID,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class ProviderType(str, enum.Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    AZURE_OPENAI = "azure_openai"
    OLLAMA = "ollama"


class ModelType(str, enum.Enum):
    CHAT = "chat"
    EMBEDDING = "embedding"
    RERANK = "rerank"


class ProviderStatus(str, enum.Enum):
    ACTIVE = "active"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class ProviderConfig(Base):
    __tablename__ = "provider_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_type: Mapped[ProviderType] = mapped_column(Enum(ProviderType), nullable=False)
    api_key: Mapped[str] = mapped_column(Text, nullable=False)  # 加密存储
    api_base: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    api_version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # Azure
    status: Mapped[ProviderStatus] = mapped_column(Enum(ProviderStatus), default=ProviderStatus.ACTIVE, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0)  # 负载均衡权重
    rate_limit_rpm: Mapped[int] = mapped_column(Integer, default=60)  # requests per minute
    rate_limit_tpm: Mapped[int] = mapped_column(Integer, default=100000)  # tokens per minute
    timeout_seconds: Mapped[float] = mapped_column(Integer, default=60)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    # "metadata" is reserved by the SQLAlchemy declarative API; keep the DB column name.
    meta: Mapped[dict] = mapped_column("metadata", JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    models: Mapped[list["ModelConfig"]] = relationship("ModelConfig", back_populates="provider", lazy="selectin")

    __table_args__ = (
        Index("ix_provider_configs_type_status", "provider_type", "status"),
        UniqueConstraint("tenant_id", "name", name="uq_provider_configs_tenant_name"),
    )


class ModelConfig(Base):
    __tablename__ = "model_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("provider_configs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g., gpt-4o-mini
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_type: Mapped[ModelType] = mapped_column(Enum(ModelType), nullable=False)
    context_window: Mapped[int] = mapped_column(Integer, default=4096)
    max_output_tokens: Mapped[int] = mapped_column(Integer, default=4096)
    supports_streaming: Mapped[bool] = mapped_column(Boolean, default=True)
    supports_functions: Mapped[bool] = mapped_column(Boolean, default=False)
    supports_vision: Mapped[bool] = mapped_column(Boolean, default=False)
    input_cost_per_1k: Mapped[float] = mapped_column(Integer, default=0)  # 存储为 micro-USD
    output_cost_per_1k: Mapped[float] = mapped_column(Integer, default=0)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # "metadata" is reserved by the SQLAlchemy declarative API; keep the DB column name.
    meta: Mapped[dict] = mapped_column("metadata", JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    provider: Mapped["ProviderConfig"] = relationship("ProviderConfig", back_populates="models", lazy="selectin")

    __table_args__ = (
        Index("ix_model_configs_type_active", "model_type", "is_active"),
        UniqueConstraint("provider_id", "name", name="uq_model_configs_provider_name"),
    )


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    provider_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("provider_configs.id"), nullable=False, index=True)
    model_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("model_configs.id"), nullable=False, index=True)
    request_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    model_type: Mapped[ModelType] = mapped_column(Enum(ModelType), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[int] = mapped_column(BigInteger, default=0)  # micro-USD
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # success, error, timeout
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # "metadata" is reserved by the SQLAlchemy declarative API; keep the DB column name.
    meta: Mapped[dict] = mapped_column("metadata", JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_usage_records_tenant_created", "tenant_id", "created_at"),
        Index("ix_usage_records_user_created", "user_id", "created_at"),
        Index("ix_usage_records_model_created", "model_id", "created_at"),
    )