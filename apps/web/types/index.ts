export interface User {
  id: string;
  tenant_id: string;
  email: string;
  full_name: string;
  role: 'SUPER_ADMIN' | 'ADMIN' | 'MEMBER' | 'VIEWER';
  is_active: boolean;
  avatar_url?: string;
  created_at: string;
  updated_at: string;
}

export interface Tenant {
  id: string;
  name: string;
  slug: string;
  settings: TenantSettings;
  created_at: string;
  updated_at: string;
}

export interface TenantSettings {
  default_model?: string;
  max_tokens_per_request?: number;
  retention_days?: number;
  allowed_domains?: string[];
  features?: {
    rag_enabled?: boolean;
    workflows_enabled?: boolean;
    analytics_enabled?: boolean;
  };
}

export interface KnowledgeBase {
  id: string;
  tenant_id?: string;
  name: string;
  description?: string;
  visibility?: 'PRIVATE' | 'TENANT' | 'PUBLIC' | string;
  status?: string;
  embedding_model?: string;
  embedding_dim?: number;
  chunk_size?: number;
  chunk_overlap?: number;
  retrieval_top_k?: number;
  retrieval_final_k?: number;
  rrf_k?: number;
  document_count: number;
  chunk_count: number;
  created_at: string;
  updated_at?: string;
}

export interface Document {
  id: string;
  knowledge_base_id: string;
  tenant_id?: string;
  /** 后端字段名：文件存储名 */
  filename: string;
  /** 后端字段名是 title，这里统一映射成展示名 */
  original_filename: string;
  title?: string;
  content_type: string;
  file_size: number;
  file_hash: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  error_message?: string;
  chunk_count: number;
  token_count: number;
  page_count: number;
  metadata: Record<string, any>;
  created_at: string;
  updated_at: string;
  completed_at?: string;
}

export interface DocumentChunk {
  id: string;
  knowledge_base_id: string;
  document_id: string;
  tenant_id: string;
  chunk_index: number;
  content: string;
  token_count: number;
  metadata: Record<string, any>;
  created_at: string;
}

export interface Conversation {
  id: string;
  tenant_id: string;
  user_id: string;
  knowledge_base_id?: string;
  title: string;
  model: string;
  system_prompt?: string;
  temperature: number;
  message_count: number;
  total_tokens: number;
  total_cost_usd: number;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: string;
  conversation_id: string;
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  tool_calls?: any[];
  tool_call_id?: string;
  tokens: number;
  cost_usd: number;
  metadata: Record<string, any>;
  created_at: string;
}

export interface ChatRequest {
  model: string;
  messages: ChatMessage[];
  temperature?: number;
  top_p?: number;
  max_tokens?: number;
  stream?: boolean;
  knowledge_base_id?: string;
  conversation_id?: string;
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export interface ChatResponse {
  id: string;
  object: string;
  created: number;
  model: string;
  choices: ChatChoice[];
  usage: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  };
}

export interface ChatChoice {
  index: number;
  message: ChatMessage;
  finish_reason: string | null;
}

export interface RetrievalRequest {
  query: string;
  knowledge_base_id: string;
  top_k?: number;
  use_rerank?: boolean;
  filters?: Record<string, any>;
}

export interface RetrievedChunk {
  chunk_id: string;
  document_id: string;
  document_filename: string;
  content: string;
  score: number;
  metadata: Record<string, any>;
}

export interface RetrievalResponse {
  query: string;
  chunks: RetrievedChunk[];
  total_found: number;
  retrieval_time_ms: number;
  rerank_time_ms?: number;
}

export interface Model {
  id: string;
  object: string;
  created: number;
  owned_by: string;
  context_window: number;
  max_output_tokens: number;
  supports_streaming: boolean;
  supports_functions: boolean;
  supports_vision: boolean;
}

export interface UsageRecord {
  id: string;
  tenant_id: string;
  user_id?: string;
  provider_id: string;
  model_id: string;
  request_id: string;
  model_type: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number;
  latency_ms: number;
  status: string;
  error_message?: string;
  created_at: string;
}

export interface CostSummary {
  total_tokens: number;
  total_cost_usd: number;
  by_model: Record<string, number>;
  by_provider: Record<string, number>;
  period_start?: string;
  period_end?: string;
}

export interface ApiError {
  detail: string;
  status_code: number;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

// Workflow Types
export interface WorkflowDefinition {
  nodes: NodeDefinition[];
  edges: EdgeDefinition[];
  viewport?: { x: number; y: number; zoom: number };
}

export interface NodeDefinition {
  id: string;
  type: string;
  name: string;
  position: { x: number; y: number };
  config: Record<string, any>;
  label?: string;
  data?: Record<string, any>;
}

export interface EdgeDefinition {
  id: string;
  source_node_id: string;
  source_port_id: string;
  target_node_id: string;
  target_port_id: string;
}

export interface WorkflowRead {
  id: string;
  tenant_id: string;
  name: string;
  description?: string;
  status: string;
  version: number;
  definition: WorkflowDefinition;
  metadata: Record<string, any>;
  created_by?: string;
  created_at: string;
  updated_at: string;
  published_at?: string;
}

export interface WorkflowNodeExecution {
  node_id: string;
  status: string;
  input?: Record<string, any> | null;
  output?: any;
  error?: string | null;
  started_at: string;
  completed_at?: string | null;
  duration_ms: number;
}

export interface WorkflowExecution {
  id: string;
  workflow_id: string;
  tenant_id: string;
  /** PENDING | RUNNING | COMPLETED | FAILED | CANCELLED */
  status: string;
  input: Record<string, any>;
  output?: Record<string, any> | null;
  error?: string | null;
  started_at: string;
  completed_at?: string | null;
  node_executions: WorkflowNodeExecution[];
}

export interface NotificationItem {
  id: string;
  tenant_id: string;
  user_id?: string | null;
  /** INFO | SUCCESS | WARNING | ERROR */
  type: string;
  /** IN_APP | EMAIL | WEBHOOK | SLACK | DINGTALK | FEISHU */
  channel: string;
  title: string;
  content: string;
  data?: Record<string, any> | null;
  read: boolean;
  sent_at?: string | null;
  created_at: string;
}
