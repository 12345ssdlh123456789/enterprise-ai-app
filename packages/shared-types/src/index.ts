// 通用类型定义 - 全项目共享

// ============ 基础类型 ============

/** 唯一标识符 */
export type UUID = string & { readonly __brand: unique symbol };

/** 时间戳 (ISO 8601) */
export type ISODateTime = string & { readonly __brand: unique symbol };

/** 分页参数 */
export interface PaginationParams {
  page: number;
  pageSize: number;
}

/** 分页响应 */
export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
}

/** API 标准响应 */
export interface ApiResponse<T = unknown> {
  success: boolean;
  data?: T;
  error?: ApiError;
  meta?: ResponseMeta;
}

/** API 错误 */
export interface ApiError {
  code: string;
  message: string;
  details?: Record<string, unknown>;
}

/** 响应元数据 */
export interface ResponseMeta {
  requestId: string;
  timestamp: ISODateTime;
  version: string;
}

// ============ 用户与认证 ============

/** 用户角色 */
export enum UserRole {
  SUPER_ADMIN = 'SUPER_ADMIN',
  ADMIN = 'ADMIN',
  MEMBER = 'MEMBER',
  VIEWER = 'VIEWER',
}

/** 用户状态 */
export enum UserStatus {
  ACTIVE = 'ACTIVE',
  INACTIVE = 'INACTIVE',
  PENDING = 'PENDING',
  SUSPENDED = 'SUSPENDED',
}

/** 用户实体 */
export interface User {
  id: UUID;
  email: string;
  username: string;
  displayName: string;
  avatarUrl?: string;
  role: UserRole;
  status: UserStatus;
  tenantId: UUID;
  lastLoginAt?: ISODateTime;
  createdAt: ISODateTime;
  updatedAt: ISODateTime;
}

/** JWT 载荷 */
export interface JwtPayload {
  sub: UUID;
  email: string;
  role: UserRole;
  tenantId: UUID;
  permissions: string[];
  iat: number;
  exp: number;
}

/** 登录凭证 */
export interface LoginCredentials {
  email: string;
  password: string;
  rememberMe?: boolean;
}

/** 登录响应 */
export interface LoginResponse {
  accessToken: string;
  refreshToken: string;
  expiresIn: number;
  tokenType: 'Bearer';
  user: User;
}

/** 权限 */
export interface Permission {
  resource: string;
  actions: string[];
}

/** 角色权限映射 */
export const ROLE_PERMISSIONS: Record<UserRole, Permission[]> = {
  [UserRole.SUPER_ADMIN]: [{ resource: '*', actions: ['*'] }],
  [UserRole.ADMIN]: [
    { resource: 'tenant', actions: ['read', 'update'] },
    { resource: 'user', actions: ['create', 'read', 'update', 'delete'] },
    { resource: 'knowledge-base', actions: ['create', 'read', 'update', 'delete'] },
    { resource: 'document', actions: ['create', 'read', 'update', 'delete'] },
    { resource: 'workflow', actions: ['create', 'read', 'update', 'delete', 'execute'] },
    { resource: 'analytics', actions: ['read'] },
  ],
  [UserRole.MEMBER]: [
    { resource: 'knowledge-base', actions: ['read'] },
    { resource: 'document', actions: ['create', 'read', 'update'] },
    { resource: 'workflow', actions: ['create', 'read', 'update', 'execute'] },
    { resource: 'chat', actions: ['create', 'read'] },
  ],
  [UserRole.VIEWER]: [
    { resource: 'knowledge-base', actions: ['read'] },
    { resource: 'document', actions: ['read'] },
    { resource: 'chat', actions: ['create', 'read'] },
  ],
};

// ============ 租户/组织 ============

/** 租户/组织 */
export interface Tenant {
  id: UUID;
  name: string;
  slug: string;
  logoUrl?: string;
  settings: TenantSettings;
  plan: TenantPlan;
  createdAt: ISODateTime;
  updatedAt: ISODateTime;
}

/** 租户设置 */
export interface TenantSettings {
  allowPublicSignup: boolean;
  defaultUserRole: UserRole;
  ssoEnabled: boolean;
  ssoProvider?: 'oauth2' | 'saml' | 'oidc';
  dataRetentionDays: number;
  maxKnowledgeBases: number;
  maxDocumentsPerKB: number;
  maxTokenBudgetMonthly: number;
}

/** 套餐计划 */
export enum TenantPlan {
  FREE = 'FREE',
  STARTER = 'STARTER',
  PROFESSIONAL = 'PROFESSIONAL',
  ENTERPRISE = 'ENTERPRISE',
}

/** 套餐限制 */
export const PLAN_LIMITS: Record<TenantPlan, Partial<TenantSettings>> = {
  [TenantPlan.FREE]: {
    maxKnowledgeBases: 3,
    maxDocumentsPerKB: 100,
    maxTokenBudgetMonthly: 100_000,
  },
  [TenantPlan.STARTER]: {
    maxKnowledgeBases: 10,
    maxDocumentsPerKB: 1_000,
    maxTokenBudgetMonthly: 1_000_000,
  },
  [TenantPlan.PROFESSIONAL]: {
    maxKnowledgeBases: 50,
    maxDocumentsPerKB: 10_000,
    maxTokenBudgetMonthly: 10_000_000,
  },
  [TenantPlan.ENTERPRISE]: {
    maxKnowledgeBases: -1, // 无限
    maxDocumentsPerKB: -1,
    maxTokenBudgetMonthly: -1,
  },
};

// ============ 知识库 ============

/** 知识库 */
export interface KnowledgeBase {
  id: UUID;
  tenantId: UUID;
  name: string;
  description?: string;
  visibility: KnowledgeBaseVisibility;
  embeddingModel: string;
  chunkSize: number;
  chunkOverlap: number;
  retrievalConfig: RetrievalConfig;
  documentCount: number;
  createdBy: UUID;
  createdAt: ISODateTime;
  updatedAt: ISODateTime;
}

/** 知识库可见性 */
export enum KnowledgeBaseVisibility {
  PRIVATE = 'PRIVATE',
  TENANT = 'TENANT',
  PUBLIC = 'PUBLIC',
}

/** 检索配置 */
export interface RetrievalConfig {
  topK: number;
  scoreThreshold: number;
  enableRerank: boolean;
  rerankModel?: string;
  hybridSearch: boolean;
  bm25Weight: number;
  vectorWeight: number;
}

/** 默认检索配置 */
export const DEFAULT_RETRIEVAL_CONFIG: RetrievalConfig = {
  topK: 5,
  scoreThreshold: 0.7,
  enableRerank: true,
  hybridSearch: true,
  bm25Weight: 0.3,
  vectorWeight: 0.7,
};

// ============ 文档 ============

/** 文档状态 */
export enum DocumentStatus {
  PENDING = 'PENDING',
  PROCESSING = 'PROCESSING',
  COMPLETED = 'COMPLETED',
  FAILED = 'FAILED',
  DELETED = 'DELETED',
}

/** 文档类型 */
export enum DocumentType {
  PDF = 'PDF',
  DOCX = 'DOCX',
  MARKDOWN = 'MARKDOWN',
  HTML = 'HTML',
  TXT = 'TXT',
  CSV = 'CSV',
  JSON = 'JSON',
  PPTX = 'PPTX',
  XLSX = 'XLSX',
}

/** 文档 */
export interface Document {
  id: UUID;
  knowledgeBaseId: UUID;
  tenantId: UUID;
  title: string;
  sourceUrl?: string;
  fileName?: string;
  fileSize?: number;
  mimeType?: string;
  type: DocumentType;
  status: DocumentStatus;
  chunkCount: number;
  tokenCount: number;
  errorMessage?: string;
  metadata: Record<string, unknown>;
  createdBy: UUID;
  createdAt: ISODateTime;
  updatedAt: ISODateTime;
  processedAt?: ISODateTime;
}

/** 文档分块 */
export interface DocumentChunk {
  id: UUID;
  documentId: UUID;
  knowledgeBaseId: UUID;
  content: string;
  tokenCount: number;
  sequence: number;
  metadata: ChunkMetadata;
  embedding?: number[];
  createdAt: ISODateTime;
}

/** 分块元数据 */
export interface ChunkMetadata {
  pageNumber?: number;
  sectionTitle?: string;
  headings?: string[];
  [key: string]: unknown;
}

// ============ 聊天/问答 ============

/** 消息角色 */
export enum MessageRole {
  SYSTEM = 'system',
  USER = 'user',
  ASSISTANT = 'assistant',
  TOOL = 'tool',
}

/** 聊天消息 */
export interface ChatMessage {
  id: UUID;
  conversationId: UUID;
  role: MessageRole;
  content: string;
  tokenCount?: number;
  model?: string;
  citations?: Citation[];
  metadata?: Record<string, unknown>;
  createdAt: ISODateTime;
}

/** 引用来源 */
export interface Citation {
  documentId: UUID;
  documentTitle: string;
  chunkId: UUID;
  chunkContent: string;
  score: number;
  pageNumber?: number;
}

/** 对话 */
export interface Conversation {
  id: UUID;
  tenantId: UUID;
  knowledgeBaseId?: UUID;
  title: string;
  model: string;
  systemPrompt?: string;
  temperature: number;
  maxTokens: number;
  messageCount: number;
  totalTokens: number;
  createdBy: UUID;
  createdAt: ISODateTime;
  updatedAt: ISODateTime;
}

/** 聊天完成请求 */
export interface ChatCompletionRequest {
  conversationId?: UUID;
  knowledgeBaseId?: UUID;
  messages: Pick<ChatMessage, 'role' | 'content'>[];
  model?: string;
  temperature?: number;
  maxTokens?: number;
  stream?: boolean;
  retrievalConfig?: Partial<RetrievalConfig>;
}

/** 聊天完成响应 (流式) */
export interface ChatCompletionChunk {
  id: string;
  conversationId: UUID;
  delta: string;
  finished: boolean;
  citations?: Citation[];
  usage?: TokenUsage;
  error?: ApiError;
}

/** Token 使用量 */
export interface TokenUsage {
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  estimatedCost?: number;
}

// ============ 工作流 ============

/** 工作流状态 */
export enum WorkflowStatus {
  DRAFT = 'DRAFT',
  ACTIVE = 'ACTIVE',
  PAUSED = 'PAUSED',
  ARCHIVED = 'ARCHIVED',
}

/** 工作流节点类型 */
export enum WorkflowNodeType {
  START = 'START',
  END = 'END',
  LLM = 'LLM',
  RETRIEVAL = 'RETRIEVAL',
  TRANSFORM = 'TRANSFORM',
  CONDITION = 'CONDITION',
  HTTP_REQUEST = 'HTTP_REQUEST',
  CODE = 'CODE',
  HUMAN_INPUT = 'HUMAN_INPUT',
}

/** 工作流节点 */
export interface WorkflowNode {
  id: string;
  type: WorkflowNodeType;
  name: string;
  position: { x: number; y: number };
  config: Record<string, unknown>;
  inputs: NodePort[];
  outputs: NodePort[];
}

/** 节点端口 */
export interface NodePort {
  id: string;
  name: string;
  type: 'string' | 'number' | 'boolean' | 'object' | 'array' | 'any';
  required: boolean;
  description?: string;
}

/** 工作流边 */
export interface WorkflowEdge {
  id: string;
  sourceNodeId: string;
  sourcePortId: string;
  targetNodeId: string;
  targetPortId: string;
}

/** 工作流定义 */
export interface WorkflowDefinition {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  variables: WorkflowVariable[];
}

/** 工作流变量 */
export interface WorkflowVariable {
  name: string;
  type: 'string' | 'number' | 'boolean' | 'object' | 'array';
  defaultValue?: unknown;
  description?: string;
  required: boolean;
}

/** 工作流 */
export interface Workflow {
  id: UUID;
  tenantId: UUID;
  name: string;
  description?: string;
  definition: WorkflowDefinition;
  status: WorkflowStatus;
  version: number;
  createdBy: UUID;
  createdAt: ISODateTime;
  updatedAt: ISODateTime;
  publishedAt?: ISODateTime;
}

/** 工作流执行 */
export interface WorkflowExecution {
  id: UUID;
  workflowId: UUID;
  tenantId: UUID;
  status: ExecutionStatus;
  input: Record<string, unknown>;
  output?: Record<string, unknown>;
  error?: string;
  startedAt: ISODateTime;
  completedAt?: ISODateTime;
  nodeExecutions: NodeExecution[];
}

/** 执行状态 */
export enum ExecutionStatus {
  PENDING = 'PENDING',
  RUNNING = 'RUNNING',
  COMPLETED = 'COMPLETED',
  FAILED = 'FAILED',
  CANCELLED = 'CANCELLED',
}

/** 节点执行记录 */
export interface NodeExecution {
  nodeId: string;
  status: ExecutionStatus;
  input?: Record<string, unknown>;
  output?: Record<string, unknown>;
  error?: string;
  startedAt: ISODateTime;
  completedAt?: ISODateTime;
  durationMs: number;
}

// ============ LLM 模型 ============

/** 模型提供商 */
export enum ModelProvider {
  OPENAI = 'OPENAI',
  ANTHROPIC = 'ANTHROPIC',
  AZURE_OPENAI = 'AZURE_OPENAI',
  OLLAMA = 'OLLAMA',
  VLLM = 'VLLM',
  CUSTOM = 'CUSTOM',
}

/** 模型能力 */
export enum ModelCapability {
  CHAT = 'CHAT',
  EMBEDDING = 'EMBEDDING',
  RERANK = 'RERANK',
  VISION = 'VISION',
  FUNCTION_CALLING = 'FUNCTION_CALLING',
  JSON_MODE = 'JSON_MODE',
}

/** 模型配置 */
export interface ModelConfig {
  id: string;
  name: string;
  provider: ModelProvider;
  capabilities: ModelCapability[];
  contextWindow: number;
  maxOutputTokens: number;
  pricing: ModelPricing;
  parameters: ModelParameters;
  enabled: boolean;
}

/** 模型定价 */
export interface ModelPricing {
  inputTokenPrice: number; // per 1M tokens
  outputTokenPrice: number; // per 1M tokens
  currency: 'USD' | 'CNY';
}

/** 模型参数 */
export interface ModelParameters {
  temperature?: { min: number; max: number; default: number };
  topP?: { min: number; max: number; default: number };
  topK?: { min: number; max: number; default: number };
  maxTokens?: { min: number; max: number; default: number };
  frequencyPenalty?: { min: number; max: number; default: number };
  presencePenalty?: { min: number; max: number; default: number };
  stopSequences?: string[];
}

/** 默认模型配置 */
export const DEFAULT_MODELS: ModelConfig[] = [
  {
    id: 'gpt-4o',
    name: 'GPT-4o',
    provider: ModelProvider.OPENAI,
    capabilities: [
      ModelCapability.CHAT,
      ModelCapability.VISION,
      ModelCapability.FUNCTION_CALLING,
      ModelCapability.JSON_MODE,
    ],
    contextWindow: 128_000,
    maxOutputTokens: 4_096,
    pricing: { inputTokenPrice: 5.0, outputTokenPrice: 15.0, currency: 'USD' },
    parameters: {
      temperature: { min: 0, max: 2, default: 0.7 },
      topP: { min: 0, max: 1, default: 1 },
      maxTokens: { min: 1, max: 4096, default: 2048 },
    },
    enabled: true,
  },
  {
    id: 'gpt-4o-mini',
    name: 'GPT-4o Mini',
    provider: ModelProvider.OPENAI,
    capabilities: [
      ModelCapability.CHAT,
      ModelCapability.VISION,
      ModelCapability.FUNCTION_CALLING,
      ModelCapability.JSON_MODE,
    ],
    contextWindow: 128_000,
    maxOutputTokens: 16_384,
    pricing: { inputTokenPrice: 0.15, outputTokenPrice: 0.6, currency: 'USD' },
    parameters: {
      temperature: { min: 0, max: 2, default: 0.7 },
      topP: { min: 0, max: 1, default: 1 },
      maxTokens: { min: 1, max: 16384, default: 2048 },
    },
    enabled: true,
  },
  {
    id: 'claude-3-5-sonnet-20241022',
    name: 'Claude 3.5 Sonnet',
    provider: ModelProvider.ANTHROPIC,
    capabilities: [ModelCapability.CHAT, ModelCapability.VISION, ModelCapability.FUNCTION_CALLING],
    contextWindow: 200_000,
    maxOutputTokens: 8_192,
    pricing: { inputTokenPrice: 3.0, outputTokenPrice: 15.0, currency: 'USD' },
    parameters: {
      temperature: { min: 0, max: 1, default: 0.7 },
      topP: { min: 0, max: 1, default: 1 },
      maxTokens: { min: 1, max: 8192, default: 2048 },
    },
    enabled: true,
  },
  {
    id: 'text-embedding-3-large',
    name: 'text-embedding-3-large',
    provider: ModelProvider.OPENAI,
    capabilities: [ModelCapability.EMBEDDING],
    contextWindow: 8_191,
    maxOutputTokens: 0,
    pricing: { inputTokenPrice: 0.13, outputTokenPrice: 0, currency: 'USD' },
    parameters: {},
    enabled: true,
  },
  {
    id: 'text-embedding-3-small',
    name: 'text-embedding-3-small',
    provider: ModelProvider.OPENAI,
    capabilities: [ModelCapability.EMBEDDING],
    contextWindow: 8_191,
    maxOutputTokens: 0,
    pricing: { inputTokenPrice: 0.02, outputTokenPrice: 0, currency: 'USD' },
    parameters: {},
    enabled: true,
  },
];

// ============ 审计日志 ============

/** 审计动作 */
export enum AuditAction {
  CREATE = 'CREATE',
  READ = 'READ',
  UPDATE = 'UPDATE',
  DELETE = 'DELETE',
  LOGIN = 'LOGIN',
  LOGOUT = 'LOGOUT',
  EXPORT = 'EXPORT',
  IMPORT = 'IMPORT',
  EXECUTE = 'EXECUTE',
}

/** 审计日志 */
export interface AuditLog {
  id: UUID;
  tenantId: UUID;
  userId: UUID;
  action: AuditAction;
  resource: string;
  resourceId?: UUID;
  oldValue?: Record<string, unknown>;
  newValue?: Record<string, unknown>;
  ipAddress?: string;
  userAgent?: string;
  success: boolean;
  errorMessage?: string;
  createdAt: ISODateTime;
}

// ============ 通知 ============

/** 通知类型 */
export enum NotificationType {
  INFO = 'INFO',
  SUCCESS = 'SUCCESS',
  WARNING = 'WARNING',
  ERROR = 'ERROR',
}

/** 通知渠道 */
export enum NotificationChannel {
  IN_APP = 'IN_APP',
  EMAIL = 'EMAIL',
  WEBHOOK = 'WEBHOOK',
  SLACK = 'SLACK',
  DINGTALK = 'DINGTALK',
  FEISHU = 'FEISHU',
}

/** 通知 */
export interface Notification {
  id: UUID;
  tenantId: UUID;
  userId?: UUID;
  type: NotificationType;
  channel: NotificationChannel;
  title: string;
  content: string;
  data?: Record<string, unknown>;
  read: boolean;
  sentAt?: ISODateTime;
  createdAt: ISODateTime;
}

// ============ 成本追踪 ============

/** 成本记录 */
export interface CostRecord {
  id: UUID;
  tenantId: UUID;
  userId?: UUID;
  modelId: string;
  modelProvider: ModelProvider;
  operationType: 'chat' | 'embedding' | 'rerank' | 'vision';
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  estimatedCost: number;
  currency: 'USD' | 'CNY';
  metadata?: Record<string, unknown>;
  createdAt: ISODateTime;
}

/** Token 预算 */
export interface TokenBudget {
  tenantId: UUID;
  period: 'daily' | 'monthly';
  limit: number;
  used: number;
  resetAt: ISODateTime;
}

// ============ 系统配置 ============

/** 系统配置键 */
export enum SystemConfigKey {
  // LLM
  DEFAULT_CHAT_MODEL = 'DEFAULT_CHAT_MODEL',
  DEFAULT_EMBEDDING_MODEL = 'DEFAULT_EMBEDDING_MODEL',
  DEFAULT_RERANK_MODEL = 'DEFAULT_RERANK_MODEL',

  // RAG
  DEFAULT_CHUNK_SIZE = 'DEFAULT_CHUNK_SIZE',
  DEFAULT_CHUNK_OVERLAP = 'DEFAULT_CHUNK_OVERLAP',
  DEFAULT_TOP_K = 'DEFAULT_TOP_K',
  DEFAULT_SCORE_THRESHOLD = 'DEFAULT_SCORE_THRESHOLD',

  // 限流
  RATE_LIMIT_REQUESTS_PER_MINUTE = 'RATE_LIMIT_REQUESTS_PER_MINUTE',
  RATE_LIMIT_TOKENS_PER_MINUTE = 'RATE_LIMIT_TOKENS_PER_MINUTE',

  // 文件上传
  MAX_FILE_SIZE_MB = 'MAX_FILE_SIZE_MB',
  ALLOWED_FILE_TYPES = 'ALLOWED_FILE_TYPES',

  // 向量数据库
  VECTOR_DB_PROVIDER = 'VECTOR_DB_PROVIDER',
  VECTOR_DB_CONNECTION = 'VECTOR_DB_CONNECTION',
}

/** 系统配置值 */
export interface SystemConfig {
  key: SystemConfigKey;
  value: string;
  description: string;
  type: 'string' | 'number' | 'boolean' | 'json';
  editable: boolean;
}
