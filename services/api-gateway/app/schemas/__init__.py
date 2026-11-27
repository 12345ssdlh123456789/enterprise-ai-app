# API Gateway - Pydantic Schemas

from datetime import datetime, timezone
from typing import Any, Dict, Generic, List, Literal, Optional, TypeVar, Union
from uuid import UUID
from decimal import Decimal

from pydantic import BaseModel, Field, EmailStr, HttpUrl, ConfigDict, field_validator
from typing_extensions import Annotated


# ============================================
# 基础配置
# ============================================

T = TypeVar("T")

def _iso_utc(value: datetime) -> str:
    """SQLite 里存的是 naive UTC，序列化时补上时区，否则前端会按本地时间解析（差 8 小时）"""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


class BaseSchema(BaseModel):
    """基础 Schema 配置"""
    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        use_enum_values=True,
        json_encoders={
            datetime: _iso_utc,
            UUID: lambda v: str(v) if v else None,
            Decimal: lambda v: float(v) if v else None,
        },
    )


class PaginationParams(BaseSchema):
    """分页参数"""
    page: int = Field(default=1, ge=1, description="页码")
    page_size: int = Field(default=20, ge=1, le=100, description="每页大小")


class PaginatedResponse(BaseSchema, Generic[T]):
    """分页响应"""
    items: List[T]
    total: int
    page: int
    page_size: int
    total_pages: int

    @classmethod
    def create(cls, items: List[Any], total: int, params: PaginationParams) -> "PaginatedResponse":
        return cls(
            items=items,
            total=total,
            page=params.page,
            page_size=params.page_size,
            total_pages=(total + params.page_size - 1) // params.page_size,
        )


class ApiResponse(BaseSchema, Generic[T]):
    """标准 API 响应"""
    success: bool = True
    data: Optional[T] = None
    error: Optional["ApiError"] = None
    meta: Optional["ResponseMeta"] = None


class ApiError(BaseSchema):
    """API 错误"""
    code: str
    message: str
    details: Optional[Dict[str, Any]] = None


class ResponseMeta(BaseSchema):
    """响应元数据"""
    request_id: str
    timestamp: datetime
    version: str = "v1"


# ============================================
# 认证相关
# ============================================

class LoginRequest(BaseSchema):
    """登录请求"""
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    remember_me: bool = False


class RegisterRequest(BaseSchema):
    """注册请求"""
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_-]+$")
    password: str = Field(..., min_length=8, max_length=128)
    display_name: Optional[str] = Field(None, max_length=100)
    tenant_slug: Optional[str] = None  # 可选，用于创建新租户


class TokenResponse(BaseSchema):
    """Token 响应"""
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "Bearer"
    user: "UserResponse"


class RefreshTokenRequest(BaseSchema):
    """刷新 Token 请求"""
    refresh_token: str


class ChangePasswordRequest(BaseSchema):
    """修改密码请求"""
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=128)


class ResetPasswordRequest(BaseSchema):
    """重置密码请求"""
    email: EmailStr


class ConfirmResetPasswordRequest(BaseSchema):
    """确认重置密码"""
    token: str
    new_password: str = Field(..., min_length=8, max_length=128)


# ============================================
# 用户相关
# ============================================

class UserBase(BaseSchema):
    """用户基础字段"""
    email: EmailStr
    username: str
    display_name: Optional[str] = None
    avatar_url: Optional[HttpUrl] = None
    role: str
    status: str


class UserCreate(BaseSchema):
    """创建用户"""
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_-]+$")
    password: str = Field(..., min_length=8, max_length=128)
    display_name: Optional[str] = Field(None, max_length=100)
    role: str = "MEMBER"


class UserUpdate(BaseSchema):
    """更新用户"""
    display_name: Optional[str] = Field(None, max_length=100)
    avatar_url: Optional[HttpUrl] = None
    role: Optional[str] = None
    status: Optional[str] = None


class UserResponse(UserBase):
    """用户响应"""
    id: UUID
    tenant_id: UUID
    last_login_at: Optional[datetime] = None
    email_verified_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class UserListResponse(BaseSchema):
    """用户列表项"""
    id: UUID
    email: str
    username: str
    display_name: Optional[str]
    avatar_url: Optional[str]
    role: str
    status: str
    last_login_at: Optional[datetime]
    created_at: datetime


# ============================================
# 租户相关
# ============================================

class TenantBase(BaseSchema):
    """租户基础字段"""
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(..., min_length=3, max_length=100, pattern=r"^[a-z0-9-]+$")
    logo_url: Optional[HttpUrl] = None


class TenantCreate(TenantBase):
    """创建租户"""
    plan: str = "FREE"
    settings: Optional[Dict[str, Any]] = None


class TenantUpdate(BaseSchema):
    """更新租户"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    logo_url: Optional[HttpUrl] = None
    settings: Optional[Dict[str, Any]] = None
    plan: Optional[str] = None


class TenantResponse(TenantBase):
    """租户响应"""
    id: UUID
    plan: str
    settings: Dict[str, Any]
    created_at: datetime
    updated_at: datetime


class TenantSettingsSchema(BaseSchema):
    """租户设置"""
    allow_public_signup: bool = False
    default_user_role: str = "MEMBER"
    sso_enabled: bool = False
    sso_provider: Optional[str] = None
    data_retention_days: int = 365
    max_knowledge_bases: int = 10
    max_documents_per_kb: int = 1000
    max_token_budget_monthly: int = 1000000


# ============================================
# 知识库相关
# ============================================

class RetrievalConfigSchema(BaseSchema):
    """检索配置"""
    top_k: int = Field(default=5, ge=1, le=50)
    score_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    enable_rerank: bool = True
    rerank_model: Optional[str] = None
    hybrid_search: bool = True
    bm25_weight: float = Field(default=0.3, ge=0.0, le=1.0)
    vector_weight: float = Field(default=0.7, ge=0.0, le=1.0)


class KnowledgeBaseBase(BaseSchema):
    """知识库基础字段"""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    visibility: str = "PRIVATE"
    embedding_model: str = "text-embedding-3-small"
    chunk_size: int = Field(default=1000, ge=100, le=8000)
    chunk_overlap: int = Field(default=200, ge=0, le=2000)
    retrieval_config: RetrievalConfigSchema = Field(default_factory=RetrievalConfigSchema)


class KnowledgeBaseCreate(KnowledgeBaseBase):
    """创建知识库"""
    pass


class KnowledgeBaseUpdate(BaseSchema):
    """更新知识库"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    visibility: Optional[str] = None
    embedding_model: Optional[str] = None
    chunk_size: Optional[int] = Field(None, ge=100, le=8000)
    chunk_overlap: Optional[int] = Field(None, ge=0, le=2000)
    retrieval_config: Optional[RetrievalConfigSchema] = None


class KnowledgeBaseResponse(KnowledgeBaseBase):
    """知识库响应"""
    id: UUID
    tenant_id: UUID
    document_count: int = 0
    chunk_count: int = 0
    token_count: int = 0
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class KnowledgeBaseListItem(BaseSchema):
    """知识库列表项"""
    id: UUID
    name: str
    description: Optional[str]
    visibility: str
    document_count: int
    chunk_count: int
    created_at: datetime


# ============================================
# 文档相关
# ============================================

class DocumentBase(BaseSchema):
    """文档基础字段"""
    title: str = Field(..., min_length=1, max_length=500)
    source_url: Optional[HttpUrl] = None


class DocumentCreate(DocumentBase):
    """创建文档"""
    knowledge_base_id: UUID
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    type: str
    metadata: Optional[Dict[str, Any]] = None


class DocumentUpdate(BaseSchema):
    """更新文档"""
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    metadata: Optional[Dict[str, Any]] = None


class DocumentResponse(DocumentBase):
    """文档响应"""
    id: UUID
    knowledge_base_id: UUID
    tenant_id: UUID
    file_name: Optional[str]
    file_size: Optional[int]
    mime_type: Optional[str]
    type: str
    status: str
    chunk_count: int = 0
    token_count: int = 0
    error_message: Optional[str]
    metadata: Dict[str, Any]
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    processed_at: Optional[datetime] = None


class DocumentListItem(BaseSchema):
    """文档列表项"""
    id: UUID
    title: str
    file_name: Optional[str]
    type: str
    status: str
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    chunk_count: int
    token_count: int
    created_at: datetime


class DocumentChunkSchema(BaseSchema):
    """文档分块"""
    id: UUID
    document_id: UUID
    content: str
    token_count: int
    sequence: int
    metadata: Dict[str, Any]
    score: Optional[float] = None


# ============================================
# 检索相关
# ============================================

class RetrievalSearchRequest(BaseSchema):
    """检索请求"""
    query: str = Field(..., min_length=1, max_length=2000)
    knowledge_base_id: UUID
    top_k: int = Field(default=5, ge=1, le=50)
    use_rerank: bool = False
    filters: Optional[Dict[str, Any]] = None


class RetrievedChunkSchema(BaseSchema):
    """检索命中的分块"""
    chunk_id: str
    document_id: str
    document_filename: str
    content: str
    score: float
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RetrievalResponseSchema(BaseSchema):
    """检索结果"""
    query: str
    chunks: List[RetrievedChunkSchema] = Field(default_factory=list)
    total_found: int = 0
    retrieval_time_ms: float = 0.0
    rerank_time_ms: Optional[float] = None


# ============================================
# 对话/聊天相关
# ============================================

class CitationSchema(BaseSchema):
    """引用来源"""
    document_id: UUID
    document_title: str
    chunk_id: UUID
    chunk_content: str
    score: float
    page_number: Optional[int] = None


class MessageBase(BaseSchema):
    """消息基础字段"""
    role: str
    content: str


class MessageCreate(MessageBase):
    """创建消息"""
    pass


class MessageResponse(MessageBase):
    """消息响应"""
    id: UUID
    conversation_id: UUID
    token_count: Optional[int] = None
    model: Optional[str] = None
    citations: Optional[List[CitationSchema]] = None
    metadata: Dict[str, Any] = {}
    created_at: datetime


class ConversationBase(BaseSchema):
    """对话基础字段"""
    title: str = Field(default="新对话", max_length=500)
    model: str = "gpt-4o-mini"
    system_prompt: Optional[str] = None
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, ge=1, le=32768)


class ConversationCreate(ConversationBase):
    """创建对话"""
    knowledge_base_id: Optional[UUID] = None


class ConversationUpdate(BaseSchema):
    """更新对话"""
    title: Optional[str] = Field(None, max_length=500)
    model: Optional[str] = None
    system_prompt: Optional[str] = None
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(None, ge=1, le=32768)


class ConversationResponse(ConversationBase):
    """对话响应"""
    id: UUID
    tenant_id: UUID
    knowledge_base_id: Optional[UUID] = None
    message_count: int = 0
    total_tokens: int = 0
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    messages: Optional[List[MessageResponse]] = None


class ConversationListItem(BaseSchema):
    """对话列表项"""
    id: UUID
    title: str
    model: str
    message_count: int
    total_tokens: int
    updated_at: datetime


# ============================================
# 聊天完成请求/响应
# ============================================

class ChatCompletionRequest(BaseSchema):
    """聊天完成请求"""
    conversation_id: Optional[UUID] = None
    knowledge_base_id: Optional[UUID] = None
    messages: List[MessageCreate]
    model: Optional[str] = None
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(None, ge=1, le=32768)
    stream: bool = True
    retrieval_config: Optional[RetrievalConfigSchema] = None


class ChatCompletionChunk(BaseSchema):
    """流式响应块"""
    id: str
    conversation_id: UUID
    delta: str
    finished: bool
    citations: Optional[List[CitationSchema]] = None
    usage: Optional["TokenUsage"] = None
    error: Optional[ApiError] = None


class TokenUsage(BaseSchema):
    """Token 使用量"""
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost: Optional[float] = None


# ============================================
# 工作流相关
# ============================================

class NodePortSchema(BaseSchema):
    """节点端口"""
    id: str
    name: str
    type: str
    required: bool = False
    description: Optional[str] = None


class WorkflowNodeSchema(BaseSchema):
    """工作流节点"""
    id: str
    type: str
    name: str
    position: Dict[str, float]  # {x, y}
    config: Dict[str, Any] = {}
    inputs: List[NodePortSchema] = []
    outputs: List[NodePortSchema] = []


class WorkflowEdgeSchema(BaseSchema):
    """工作流边"""
    id: str
    source_node_id: str
    source_port_id: str
    target_node_id: str
    target_port_id: str


class WorkflowVariableSchema(BaseSchema):
    """工作流变量"""
    name: str
    type: str
    default_value: Optional[Any] = None
    description: Optional[str] = None
    required: bool = False


class WorkflowDefinitionSchema(BaseSchema):
    """工作流定义"""
    nodes: List[WorkflowNodeSchema] = []
    edges: List[WorkflowEdgeSchema] = []
    variables: List[WorkflowVariableSchema] = []


class WorkflowBase(BaseSchema):
    """工作流基础字段"""
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    definition: WorkflowDefinitionSchema = Field(default_factory=WorkflowDefinitionSchema)


class WorkflowCreate(WorkflowBase):
    """创建工作流"""
    pass


class WorkflowUpdate(BaseSchema):
    """更新工作流"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    definition: Optional[WorkflowDefinitionSchema] = None
    status: Optional[str] = None


class WorkflowResponse(WorkflowBase):
    """工作流响应"""
    id: UUID
    tenant_id: UUID
    status: str
    version: int = 1
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    published_at: Optional[datetime] = None


class WorkflowListItem(BaseSchema):
    """工作流列表项"""
    id: UUID
    name: str
    description: Optional[str]
    status: str
    version: int
    created_at: datetime
    updated_at: datetime


class WorkflowExecutionRequest(BaseSchema):
    """工作流执行请求"""
    input: Dict[str, Any] = {}
    # 前端历史上用的是 input_data，保留兼容
    input_data: Optional[Dict[str, Any]] = None


class NodeExecutionSchema(BaseSchema):
    """节点执行记录"""
    node_id: str
    status: str
    input: Optional[Dict[str, Any]] = None
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_ms: int = 0


class WorkflowExecutionResponse(BaseSchema):
    """工作流执行响应"""
    id: UUID
    workflow_id: UUID
    tenant_id: UUID
    status: str
    input: Dict[str, Any]
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    node_executions: List[NodeExecutionSchema] = []


# ============================================
# 模型相关
# ============================================

class ModelPricingSchema(BaseSchema):
    """模型定价"""
    input_token_price: float  # per 1M tokens
    output_token_price: float
    currency: str = "USD"


class ModelParametersSchema(BaseSchema):
    """模型参数"""
    temperature: Optional[Dict[str, float]] = None
    top_p: Optional[Dict[str, float]] = None
    top_k: Optional[Dict[str, int]] = None
    max_tokens: Optional[Dict[str, int]] = None
    frequency_penalty: Optional[Dict[str, float]] = None
    presence_penalty: Optional[Dict[str, float]] = None
    stop_sequences: Optional[List[str]] = None


class ModelSchema(BaseSchema):
    """模型配置"""
    id: str
    name: str
    provider: str
    capabilities: List[str]
    context_window: int
    max_output_tokens: int
    pricing: ModelPricingSchema
    parameters: ModelParametersSchema
    enabled: bool = True


# ============================================
# 审计日志
# ============================================

class AuditLogSchema(BaseSchema):
    """审计日志"""
    id: UUID
    tenant_id: UUID
    user_id: Optional[UUID]
    action: str
    resource: str
    resource_id: Optional[UUID]
    old_value: Optional[Dict[str, Any]]
    new_value: Optional[Dict[str, Any]]
    ip_address: Optional[str]
    user_agent: Optional[str]
    success: bool
    error_message: Optional[str]
    created_at: datetime


# ============================================
# 通知相关
# ============================================

class NotificationSchema(BaseSchema):
    """通知"""
    id: UUID
    tenant_id: UUID
    user_id: Optional[UUID]
    type: str
    channel: str
    title: str
    content: str
    data: Optional[Dict[str, Any]]
    read: bool
    sent_at: Optional[datetime]
    created_at: datetime


class NotificationCreate(BaseSchema):
    """创建通知"""
    user_id: Optional[UUID] = None
    type: str = "INFO"
    channel: str = "IN_APP"
    title: str
    content: str
    data: Optional[Dict[str, Any]] = None


# ============================================
# 成本追踪
# ============================================

class CostRecordSchema(BaseSchema):
    """成本记录"""
    id: UUID
    tenant_id: UUID
    user_id: Optional[UUID]
    model_id: str
    model_provider: str
    operation_type: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost: float
    currency: str
    metadata: Optional[Dict[str, Any]]
    created_at: datetime


class TokenBudgetSchema(BaseSchema):
    """Token 预算"""
    tenant_id: UUID
    period: str
    limit: int
    used: int
    reset_at: datetime
    usage_percentage: float


# ============================================
# 系统配置
# ============================================

class SystemConfigSchema(BaseSchema):
    """系统配置"""
    key: str
    value: str
    description: Optional[str]
    type: str
    editable: bool


class SystemConfigUpdate(BaseSchema):
    """更新系统配置"""
    value: str


# ============================================
# API Key
# ============================================

class APIKeyCreate(BaseSchema):
    """创建 API Key"""
    name: str = Field(..., min_length=1, max_length=255)
    permissions: Dict[str, Any] = {}
    expires_at: Optional[datetime] = None


class APIKeyResponse(BaseSchema):
    """API Key 响应 (仅创建时返回完整 key)"""
    id: UUID
    key: str  # 仅创建时返回
    key_prefix: str
    name: str
    permissions: Dict[str, Any]
    expires_at: Optional[datetime]
    created_at: datetime


class APIKeyListItem(BaseSchema):
    """API Key 列表项"""
    id: UUID
    key_prefix: str
    name: str
    permissions: Dict[str, Any]
    expires_at: Optional[datetime]
    last_used_at: Optional[datetime]
    created_at: datetime
    revoked_at: Optional[datetime]


# ============================================
# 健康检查
# ============================================

class HealthCheckResponse(BaseSchema):
    """健康检查响应"""
    status: Literal["healthy", "degraded", "unhealthy"]
    version: str
    timestamp: datetime
    checks: Dict[str, "ServiceHealthCheck"]


class ServiceHealthCheck(BaseSchema):
    """服务健康检查"""
    status: Literal["healthy", "degraded", "unhealthy"]
    latency_ms: Optional[float] = None
    details: Optional[Dict[str, Any]] = None


# ============================================
# 文件上传
# ============================================

class FileUploadResponse(BaseSchema):
    """文件上传响应"""
    file_id: UUID
    file_name: str
    file_size: int
    mime_type: str
    url: str


# 前向引用解析
TokenResponse.model_rebuild()