# API Gateway - Database Models (SQLAlchemy 2.0)

import enum
import uuid
from datetime import datetime, timezone
from typing import Optional, List, TYPE_CHECKING
from decimal import Decimal

from sqlalchemy import (
    String, Text, Integer, BigInteger, Boolean, DateTime, Enum,
    ForeignKey, Index, UniqueConstraint, CheckConstraint,
    JSON, ARRAY, func, text
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, declared_attr

from app.db.session import Base
from app.db.types import GUID as PG_UUID
from app.db.types import InetType as INET
from app.db.types import JSONType as JSONB


# ============================================
# 枚举定义
# ============================================

class UserRole(str, enum.Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"
    VIEWER = "VIEWER"


class UserStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    PENDING = "PENDING"
    SUSPENDED = "SUSPENDED"


class TenantPlan(str, enum.Enum):
    FREE = "FREE"
    STARTER = "STARTER"
    PROFESSIONAL = "PROFESSIONAL"
    ENTERPRISE = "ENTERPRISE"


class KBVisibility(str, enum.Enum):
    PRIVATE = "PRIVATE"
    TENANT = "TENANT"
    PUBLIC = "PUBLIC"


class DocumentStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DELETED = "DELETED"


class DocumentType(str, enum.Enum):
    PDF = "PDF"
    DOCX = "DOCX"
    MARKDOWN = "MARKDOWN"
    HTML = "HTML"
    TXT = "TXT"
    CSV = "CSV"
    JSON = "JSON"
    PPTX = "PPTX"
    XLSX = "XLSX"


class MessageRole(str, enum.Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class WorkflowStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ARCHIVED = "ARCHIVED"


class WorkflowNodeType(str, enum.Enum):
    START = "START"
    END = "END"
    LLM = "LLM"
    RETRIEVAL = "RETRIEVAL"
    TRANSFORM = "TRANSFORM"
    CONDITION = "CONDITION"
    HTTP_REQUEST = "HTTP_REQUEST"
    CODE = "CODE"
    HUMAN_INPUT = "HUMAN_INPUT"


class ExecutionStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ModelProvider(str, enum.Enum):
    OPENAI = "OPENAI"
    ANTHROPIC = "ANTHROPIC"
    AZURE_OPENAI = "AZURE_OPENAI"
    OLLAMA = "OLLAMA"
    VLLM = "VLLM"
    CUSTOM = "CUSTOM"


class ModelCapability(str, enum.Enum):
    CHAT = "CHAT"
    EMBEDDING = "EMBEDDING"
    RERANK = "RERANK"
    VISION = "VISION"
    FUNCTION_CALLING = "FUNCTION_CALLING"
    JSON_MODE = "JSON_MODE"


class AuditAction(str, enum.Enum):
    CREATE = "CREATE"
    READ = "READ"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"
    EXPORT = "EXPORT"
    IMPORT = "IMPORT"
    EXECUTE = "EXECUTE"


class NotificationType(str, enum.Enum):
    INFO = "INFO"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    ERROR = "ERROR"


class NotificationChannel(str, enum.Enum):
    IN_APP = "IN_APP"
    EMAIL = "EMAIL"
    WEBHOOK = "WEBHOOK"
    SLACK = "SLACK"
    DINGTALK = "DINGTALK"
    FEISHU = "FEISHU"


class ConfigType(str, enum.Enum):
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    JSON = "json"


# ============================================
# Mixin 类
# ============================================

class TimestampMixin:
    """时间戳混入"""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class SoftDeleteMixin:
    """软删除混入"""
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class UUIDMixin:
    """UUID 主键混入"""
    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )


# ============================================
# 核心模型
# ============================================

class Tenant(UUIDMixin, TimestampMixin, Base):
    """租户/组织"""
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    logo_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    plan: Mapped[TenantPlan] = mapped_column(
        Enum(TenantPlan, native_enum=False),
        nullable=False,
        default=TenantPlan.FREE,
    )

    # 关系
    users: Mapped[List["User"]] = relationship(back_populates="tenant", lazy="dynamic")
    knowledge_bases: Mapped[List["KnowledgeBase"]] = relationship(back_populates="tenant", lazy="dynamic")
    documents: Mapped[List["Document"]] = relationship(back_populates="tenant", lazy="dynamic")
    conversations: Mapped[List["Conversation"]] = relationship(back_populates="tenant", lazy="dynamic")
    workflows: Mapped[List["Workflow"]] = relationship(back_populates="tenant", lazy="dynamic")
    audit_logs: Mapped[List["AuditLog"]] = relationship(back_populates="tenant", lazy="dynamic")
    notifications: Mapped[List["Notification"]] = relationship(back_populates="tenant", lazy="dynamic")
    cost_records: Mapped[List["CostRecord"]] = relationship(back_populates="tenant", lazy="dynamic")
    token_budget: Mapped[Optional["TokenBudget"]] = relationship(back_populates="tenant", uselist=False)
    api_keys: Mapped[List["APIKey"]] = relationship(back_populates="tenant", lazy="dynamic")

    __table_args__ = (
        Index("ix_tenants_plan", "plan"),
    )


class User(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    """用户"""
    __tablename__ = "users"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, native_enum=False),
        nullable=False,
        default=UserRole.MEMBER,
    )
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus, native_enum=False),
        nullable=False,
        default=UserStatus.PENDING,
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # 关系
    tenant: Mapped["Tenant"] = relationship(back_populates="users")
    created_knowledge_bases: Mapped[List["KnowledgeBase"]] = relationship(back_populates="created_by_user", foreign_keys="KnowledgeBase.created_by")
    created_documents: Mapped[List["Document"]] = relationship(back_populates="created_by_user", foreign_keys="Document.created_by")
    created_conversations: Mapped[List["Conversation"]] = relationship(back_populates="created_by_user", foreign_keys="Conversation.created_by")
    created_workflows: Mapped[List["Workflow"]] = relationship(back_populates="created_by_user", foreign_keys="Workflow.created_by")
    audit_logs: Mapped[List["AuditLog"]] = relationship(back_populates="user", foreign_keys="AuditLog.user_id")
    notifications: Mapped[List["Notification"]] = relationship(back_populates="user", foreign_keys="Notification.user_id")
    cost_records: Mapped[List["CostRecord"]] = relationship(back_populates="user", foreign_keys="CostRecord.user_id")
    refresh_tokens: Mapped[List["RefreshToken"]] = relationship(back_populates="user", lazy="dynamic")
    created_api_keys: Mapped[List["APIKey"]] = relationship(back_populates="created_by_user", foreign_keys="APIKey.created_by")

    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
        UniqueConstraint("tenant_id", "username", name="uq_users_tenant_username"),
        Index("ix_users_email", "email"),
        Index("ix_users_status", "status"),
    )


class KnowledgeBase(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    """知识库"""
    __tablename__ = "knowledge_bases"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    visibility: Mapped[KBVisibility] = mapped_column(
        Enum(KBVisibility, native_enum=False),
        nullable=False,
        default=KBVisibility.PRIVATE,
    )
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False, default="text-embedding-3-small")
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    chunk_overlap: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    retrieval_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    document_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_by: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )

    # 关系
    tenant: Mapped["Tenant"] = relationship(back_populates="knowledge_bases")
    created_by_user: Mapped["User"] = relationship(back_populates="created_knowledge_bases", foreign_keys=[created_by])
    documents: Mapped[List["Document"]] = relationship(back_populates="knowledge_base", lazy="dynamic")
    chunks: Mapped[List["DocumentChunk"]] = relationship(back_populates="knowledge_base", lazy="dynamic")
    conversations: Mapped[List["Conversation"]] = relationship(back_populates="knowledge_base", lazy="dynamic")

    __table_args__ = (
        Index("ix_knowledge_bases_visibility", "visibility"),
        Index("ix_knowledge_bases_created_by", "created_by"),
    )


class Document(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    """文档"""
    __tablename__ = "documents"

    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_name: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    type: Mapped[DocumentType] = mapped_column(
        Enum(DocumentType, native_enum=False),
        nullable=False,
    )
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, native_enum=False),
        nullable=False,
        default=DocumentStatus.PENDING,
    )
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_by: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # 关系
    knowledge_base: Mapped["KnowledgeBase"] = relationship(back_populates="documents")
    tenant: Mapped["Tenant"] = relationship(back_populates="documents")
    created_by_user: Mapped["User"] = relationship(back_populates="created_documents", foreign_keys=[created_by])
    chunks: Mapped[List["DocumentChunk"]] = relationship(back_populates="document", lazy="dynamic")

    __table_args__ = (
        Index("ix_documents_status", "status"),
        Index("ix_documents_created_by", "created_by"),
        Index("ix_documents_type", "type"),
    )


class DocumentChunk(UUIDMixin, TimestampMixin, Base):
    """文档分块 (带向量)"""
    __tablename__ = "document_chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    embedding: Mapped[Optional[List[float]]] = mapped_column(
        JSONB,  # 存为 JSON 数组，pgvector 用 vector 类型
        nullable=True,
    )

    # 关系
    document: Mapped["Document"] = relationship(back_populates="chunks")
    knowledge_base: Mapped["KnowledgeBase"] = relationship(back_populates="chunks")

    __table_args__ = (
        Index("ix_chunks_sequence", "document_id", "sequence"),
    )


class Conversation(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    """对话"""
    __tablename__ = "conversations"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    knowledge_base_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="新对话")
    model: Mapped[str] = mapped_column(String(100), nullable=False, default="gpt-4o-mini")
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    temperature: Mapped[Decimal] = mapped_column(default=Decimal("0.70"), nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=2048)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_by: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )

    # 关系
    tenant: Mapped["Tenant"] = relationship(back_populates="conversations")
    knowledge_base: Mapped[Optional["KnowledgeBase"]] = relationship(back_populates="conversations")
    created_by_user: Mapped["User"] = relationship(back_populates="created_conversations", foreign_keys=[created_by])
    messages: Mapped[List["Message"]] = relationship(back_populates="conversation", lazy="dynamic", order_by="Message.created_at")

    __table_args__ = (
        Index("ix_conversations_created_by", "created_by"),
    )


class Message(UUIDMixin, TimestampMixin, Base):
    """消息"""
    __tablename__ = "messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[MessageRole] = mapped_column(
        Enum(MessageRole, native_enum=False),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    citations: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    # 关系
    conversation: Mapped["Conversation"] = relationship(back_populates="messages")

    __table_args__ = (
        Index("ix_messages_created_at", "created_at"),
    )


class Workflow(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    """工作流"""
    __tablename__ = "workflows"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[WorkflowStatus] = mapped_column(
        Enum(WorkflowStatus, native_enum=False),
        nullable=False,
        default=WorkflowStatus.DRAFT,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # 关系
    tenant: Mapped["Tenant"] = relationship(back_populates="workflows")
    created_by_user: Mapped["User"] = relationship(back_populates="created_workflows", foreign_keys=[created_by])
    executions: Mapped[List["WorkflowExecution"]] = relationship(back_populates="workflow", lazy="dynamic")

    __table_args__ = (
        Index("ix_workflows_status", "status"),
        Index("ix_workflows_created_by", "created_by"),
    )


class WorkflowExecution(UUIDMixin, TimestampMixin, Base):
    """工作流执行"""
    __tablename__ = "workflow_executions"

    workflow_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[ExecutionStatus] = mapped_column(
        Enum(ExecutionStatus, native_enum=False),
        nullable=False,
        default=ExecutionStatus.PENDING,
    )
    input: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    output: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # 节点级执行明细（列表）；历史行是 `{}`，读的时候统一兜底成 []
    node_executions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # 关系
    workflow: Mapped["Workflow"] = relationship(back_populates="executions")

    __table_args__ = (
        Index("ix_workflow_executions_status", "status"),
        Index("ix_workflow_executions_started_at", "started_at"),
    )


class Model(UUIDMixin, TimestampMixin, Base):
    """模型配置"""
    __tablename__ = "models"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)  # 使用字符串 ID
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[ModelProvider] = mapped_column(
        Enum(ModelProvider, native_enum=False),
        nullable=False,
    )
    capabilities: Mapped[List[ModelCapability]] = mapped_column(
        JSONB,  # SQLite 下为 JSON 数组，PostgreSQL 下为 JSONB
        nullable=False,
        default=list,
    )
    context_window: Mapped[int] = mapped_column(Integer, nullable=False)
    max_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    pricing: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        Index("ix_models_provider", "provider"),
        Index("ix_models_enabled", "enabled"),
    )


class AuditLog(UUIDMixin, Base):
    """审计日志"""
    __tablename__ = "audit_logs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action: Mapped[AuditAction] = mapped_column(
        Enum(AuditAction, native_enum=False),
        nullable=False,
    )
    resource: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[Optional[uuid.UUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    old_value: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(INET, nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    # 关系
    tenant: Mapped["Tenant"] = relationship(back_populates="audit_logs")
    user: Mapped[Optional["User"]] = relationship(back_populates="audit_logs", foreign_keys=[user_id])

    __table_args__ = (
        Index("ix_audit_logs_action", "action"),
        Index("ix_audit_logs_resource", "resource", "resource_id"),
    )


class Notification(UUIDMixin, TimestampMixin, Base):
    """通知"""
    __tablename__ = "notifications"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType, native_enum=False),
        nullable=False,
    )
    channel: Mapped[NotificationChannel] = mapped_column(
        Enum(NotificationChannel, native_enum=False),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # 关系
    tenant: Mapped["Tenant"] = relationship(back_populates="notifications")
    user: Mapped[Optional["User"]] = relationship(back_populates="notifications", foreign_keys=[user_id])

    __table_args__ = (
        Index("ix_notifications_read", "read"),
        Index("ix_notifications_created_at", "created_at"),
    )


class CostRecord(UUIDMixin, Base):
    """成本记录"""
    __tablename__ = "cost_records"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    model_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    model_provider: Mapped[ModelProvider] = mapped_column(
        Enum(ModelProvider, native_enum=False),
        nullable=False,
    )
    operation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost: Mapped[Decimal] = mapped_column(default=Decimal("0"), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    meta: Mapped[Optional[dict]] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    # 关系
    tenant: Mapped["Tenant"] = relationship(back_populates="cost_records")
    user: Mapped[Optional["User"]] = relationship(back_populates="cost_records", foreign_keys=[user_id])

    __table_args__ = (
    )


class TokenBudget(Base):
    """Token 预算"""
    __tablename__ = "token_budgets"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    period: Mapped[str] = mapped_column(String(20), nullable=False)  # daily, monthly
    limit: Mapped[int] = mapped_column(BigInteger, nullable=False)
    used: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    reset_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # 关系
    tenant: Mapped["Tenant"] = relationship(back_populates="token_budget")

    __table_args__ = (
        CheckConstraint("period IN ('daily', 'monthly')", name="ck_token_budgets_period"),
    )


class SystemConfig(Base):
    """系统配置"""
    __tablename__ = "system_configs"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    type: Mapped[ConfigType] = mapped_column(
        Enum(ConfigType, native_enum=False),
        nullable=False,
        default=ConfigType.STRING,
    )
    editable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class RefreshToken(UUIDMixin, Base):
    """刷新 Token"""
    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # 关系
    user: Mapped["User"] = relationship(back_populates="refresh_tokens")

    __table_args__ = (
    )


class APIKey(UUIDMixin, TimestampMixin, Base):
    """API Key"""
    __tablename__ = "api_keys"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    key_prefix: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    permissions: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # 关系
    tenant: Mapped["Tenant"] = relationship(back_populates="api_keys")
    created_by_user: Mapped["User"] = relationship(back_populates="created_api_keys", foreign_keys=[created_by])

    __table_args__ = (
    )
