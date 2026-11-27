import axios, { AxiosInstance, InternalAxiosRequestConfig, AxiosError } from 'axios';
import { ApiError, NotificationItem, WorkflowExecution } from '@/types';

// 网关默认端口是 8000；以前这里写成了 8200，只有本机 .env.local 覆盖时才碰巧能跑
// （CI / 新克隆没有 .env.local，会直接连不上）。
const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000/api/v1';

export interface ChatCompletionPayload {
  model: string;
  messages: Array<{ role: string; content: string }>;
  temperature?: number;
  top_p?: number;
  max_tokens?: number;
  stream?: boolean;
  conversation_id?: string;
  knowledge_base_id?: string;
}

// 后端分页参数是 page/page_size，而页面里用的是 skip/limit，这里统一转换（否则 limit 会被忽略，永远只返回 20 条）
function toPageParams(params?: { skip?: number; limit?: number } & Record<string, any>) {
  if (!params) return undefined;
  const { skip, limit, ...rest } = params;
  const pageSize = limit ?? 20;
  return {
    ...rest,
    page: skip && pageSize ? Math.floor(skip / pageSize) + 1 : 1,
    page_size: pageSize,
  };
}

class ApiClient {
  private client: AxiosInstance;
  private refreshPromise: Promise<string> | null = null;

  constructor() {
    this.client = axios.create({
      baseURL: API_URL,
      headers: {
        'Content-Type': 'application/json',
      },
      timeout: 60000,
    });

    this.setupInterceptors();
  }

  private setupInterceptors() {
    // Request interceptor - add auth token
    this.client.interceptors.request.use(
      (config: InternalAxiosRequestConfig) => {
        const token = typeof window !== 'undefined' ? localStorage.getItem('access_token') : null;
        if (token && config.headers) {
          config.headers.Authorization = `Bearer ${token}`;
        }
        return config;
      },
      (error) => Promise.reject(error)
    );

    // Response interceptor - handle 401 and token refresh
    this.client.interceptors.response.use(
      (response) => {
        // The gateway wraps every payload as { success, data, error, meta };
        // unwrap it (and paginated { items: [...] } bodies) for the UI.
        const body: any = response.data;
        if (body && typeof body === 'object' && !Array.isArray(body) && 'success' in body && 'data' in body) {
          const inner = body.data;
          response.data = inner && typeof inner === 'object' && Array.isArray(inner.items) ? inner.items : inner;
        }
        return response;
      },
      async (error: AxiosError<ApiError>) => {
        const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean };

        if (error.response?.status === 401 && !originalRequest._retry) {
          originalRequest._retry = true;

          try {
            const newToken = await this.refreshAccessToken();
            if (originalRequest.headers) {
              originalRequest.headers.Authorization = `Bearer ${newToken}`;
            }
            return this.client(originalRequest);
          } catch {
            // Refresh failed, redirect to login
            if (typeof window !== 'undefined') {
              localStorage.removeItem('access_token');
              localStorage.removeItem('refresh_token');
              // 项目没有独立的 /login 页面，登录表单在首页
              window.location.href = '/';
            }
            return Promise.reject(error);
          }
        }

        return Promise.reject(error);
      }
    );
  }

  private async refreshAccessToken(): Promise<string> {
    if (this.refreshPromise) {
      return this.refreshPromise;
    }

    const refreshToken = typeof window !== 'undefined' ? localStorage.getItem('refresh_token') : null;
    if (!refreshToken) {
      throw new Error('No refresh token');
    }

    this.refreshPromise = (async () => {
      const res = await axios.post(`${API_URL}/auth/refresh`, { refresh_token: refreshToken });
      const { access_token } = res.data;
      if (typeof window !== 'undefined') {
        localStorage.setItem('access_token', access_token);
      }
      return access_token;
    })();

    try {
      return await this.refreshPromise;
    } finally {
      this.refreshPromise = null;
    }
  }

  // Auth
  async login(email: string, password: string) {
    const res = await this.client.post('/auth/login', { email, password });
    return res.data;
  }

  async register(data: { email: string; password: string; full_name: string; tenant_name?: string }) {
    const res = await this.client.post('/auth/register', data);
    return res.data;
  }

  async logout() {
    const res = await this.client.post('/auth/logout');
    return res.data;
  }

  async getMe() {
    const res = await this.client.get('/auth/me');
    return res.data;
  }

  async changePassword(current_password: string, new_password: string) {
    const res = await this.client.post('/auth/change-password', { current_password, new_password });
    return res.data;
  }

  // Users
  async getUsers(params?: { skip?: number; limit?: number }) {
    const res = await this.client.get('/users', { params: toPageParams(params) });
    return res.data;
  }

  async getUser(id: string) {
    const res = await this.client.get(`/users/${id}`);
    return res.data;
  }

  // Tenants
  async getTenant() {
    const res = await this.client.get('/tenants/me');
    return res.data;
  }

  async updateTenant(data: Partial<{ name: string; settings: any }>) {
    const res = await this.client.patch('/tenants/me', data);
    return res.data;
  }

  // Knowledge Bases
  async getKnowledgeBases(params?: { skip?: number; limit?: number }) {
    const res = await this.client.get('/knowledge-bases', { params: toPageParams(params) });
    return res.data;
  }

  async getKnowledgeBase(id: string) {
    const res = await this.client.get(`/knowledge-bases/${id}`);
    return res.data;
  }

  async createKnowledgeBase(data: {
    name: string;
    description?: string;
    embedding_model?: string;
    embedding_dim?: number;
    chunk_size?: number;
    chunk_overlap?: number;
    retrieval_top_k?: number;
    retrieval_final_k?: number;
    rrf_k?: number;
  }) {
    const res = await this.client.post('/knowledge-bases', data);
    return res.data;
  }

  async updateKnowledgeBase(id: string, data: Partial<{
    name: string;
    description: string;
    chunk_size: number;
    chunk_overlap: number;
    retrieval_top_k: number;
    retrieval_final_k: number;
    rrf_k: number;
  }>) {
    const res = await this.client.patch(`/knowledge-bases/${id}`, data);
    return res.data;
  }

  async deleteKnowledgeBase(id: string) {
    const res = await this.client.delete(`/knowledge-bases/${id}`);
    return res.data;
  }

  // Documents
  async getDocuments(kbId: string, params?: { skip?: number; limit?: number }) {
    // 后端参数名是 knowledge_base_id（原来传 kb_id 会被忽略，导致列出所有知识库的文档）
    const res = await this.client.get('/documents', {
      params: toPageParams({ knowledge_base_id: kbId, ...params }),
    });
    const raw = res.data as any;
    const items: any[] = Array.isArray(raw) ? raw : raw?.items ?? [];
    // 后端 DocumentListItem 与前端 Document 字段名不同，这里统一映射一次
    return items.map((d: any) => ({
      ...d,
      filename: d.file_name ?? d.filename ?? '',
      original_filename: d.title ?? d.original_filename ?? d.file_name ?? '',
      content_type: d.mime_type ?? d.content_type ?? '',
      file_size: d.file_size ?? 0,
      file_hash: d.metadata?.file_hash ?? d.file_hash ?? '',
      status: String(d.status ?? 'pending').toLowerCase(),
      chunk_count: d.chunk_count ?? 0,
      token_count: d.token_count ?? 0,
      page_count: d.page_count ?? 0,
      metadata: d.metadata ?? {},
      knowledge_base_id: d.knowledge_base_id ?? kbId,
    }));
  }

  async getDocument(id: string) {
    const res = await this.client.get(`/documents/${id}`);
    return res.data;
  }

  async createDocument(data: {
    knowledge_base_id: string;
    filename: string;
    original_filename: string;
    content_type: string;
    file_size: number;
    file_hash: string;
  }) {
    // 后端 DocumentCreate 需要 title / type（枚举大写），这里做一次映射
    const typeMap: Record<string, string> = {
      pdf: 'PDF', docx: 'DOCX', md: 'MARKDOWN', markdown: 'MARKDOWN',
      html: 'HTML', htm: 'HTML', txt: 'TXT', csv: 'CSV', json: 'JSON',
      pptx: 'PPTX', xlsx: 'XLSX',
    };
    const ext = (data.filename.split('.').pop() || '').toLowerCase();
    const res = await this.client.post('/documents', {
      knowledge_base_id: data.knowledge_base_id,
      title: data.original_filename || data.filename,
      type: typeMap[ext] || 'TXT',
      file_name: data.filename,
      file_size: data.file_size,
      mime_type: data.content_type,
      metadata: data.file_hash ? { file_hash: data.file_hash } : undefined,
    });
    return res.data;
  }

  async deleteDocument(id: string) {
    const res = await this.client.delete(`/documents/${id}`);
    return res.data;
  }

  async processDocument(id: string, force_reprocess = false) {
    const res = await this.client.post(`/documents/${id}/reprocess`, { force_reprocess });
    return res.data;
  }

  // 网关上传统一用 multipart（/documents/upload），上传后立即解析分块
  async uploadDocument(
    file: File,
    knowledgeBaseId: string,
    onProgress?: (percent: number) => void
  ) {
    const form = new FormData();
    form.append('file', file);
    form.append('knowledge_base_id', knowledgeBaseId);
    form.append('title', file.name);

    const res = await this.client.post('/documents/upload', form, {
      timeout: 300000,
      onUploadProgress: (event) => {
        if (event.total) onProgress?.(Math.round((event.loaded / event.total) * 100));
      },
    });
    return res.data;
  }

  async getDocumentChunks(docId: string, params?: { skip?: number; limit?: number }) {
    const res = await this.client.get(`/documents/${docId}/chunks`, { params: toPageParams(params) });
    return res.data;
  }

  // Retrieval
  async search(data: {
    query: string;
    knowledge_base_id: string;
    top_k?: number;
    use_rerank?: boolean;
    filters?: Record<string, any>;
  }) {
    const res = await this.client.post('/retrieval/search', data);
    return res.data;
  }

  // Chat / Conversations
  async getConversations(params?: { skip?: number; limit?: number }) {
    const res = await this.client.get('/conversations', { params: toPageParams(params) });
    return res.data;
  }

  async getConversation(id: string) {
    const res = await this.client.get(`/conversations/${id}`);
    return res.data;
  }

  async createConversation(data: {
    knowledge_base_id?: string;
    title: string;
    model?: string;
    system_prompt?: string;
    temperature?: number;
  }) {
    const res = await this.client.post('/conversations', data);
    return res.data;
  }

  async updateConversation(id: string, data: Partial<{
    title: string;
    model: string;
    system_prompt: string;
    temperature: number;
  }>) {
    const res = await this.client.patch(`/conversations/${id}`, data);
    return res.data;
  }

  async deleteConversation(id: string) {
    const res = await this.client.delete(`/conversations/${id}`);
    return res.data;
  }

  async getMessages(conversationId: string, params?: { skip?: number; limit?: number }) {
    const res = await this.client.get(`/conversations/${conversationId}/messages`, { params: toPageParams(params) });
    return res.data;
  }

  async sendMessage(conversationId: string, data: {
    content: string;
    model?: string;
    temperature?: number;
    stream?: boolean;
  }) {
    const res = await this.client.post(`/conversations/${conversationId}/messages`, data);
    return res.data;
  }

  // Models
  async getModels() {
    const res = await this.client.get('/models');
    return res.data;
  }

  async getDefaultModel() {
    const res = await this.client.get('/models/defaults/chat');
    return res.data;
  }

  // Chat completion (gateway route: /conversations/chat/completions)
  async chatCompletion(data: ChatCompletionPayload) {
    const res = await this.client.post('/conversations/chat/completions', { ...data, stream: false });
    return res.data;
  }

  async streamChatCompletion(data: ChatCompletionPayload, onChunk: (chunk: any) => void) {
    const res = await fetch(`${API_URL}/conversations/chat/completions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${localStorage.getItem('access_token')}`,
      },
      body: JSON.stringify({ ...data, stream: true }),
    });

    if (!res.ok) {
      let detail = 'Stream failed';
      try {
        const body = await res.json();
        detail = body?.detail || body?.error?.message || detail;
      } catch {
        /* keep default message */
      }
      throw new Error(detail);
    }

    const reader = res.body?.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (reader) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      // SSE events are separated by a blank line
      const events = buffer.split('\n\n');
      buffer = events.pop() || '';

      for (const event of events) {
        for (const line of event.split('\n')) {
          if (!line.startsWith('data:')) continue;
          const payload = line.slice(5).trim();
          if (!payload || payload === '[DONE]') continue;
          try {
            onChunk(JSON.parse(payload));
          } catch {
            /* ignore malformed keep-alive frames */
          }
        }
      }
    }
  }

  // Usage & Cost
  async getUsageRecords(params?: {
    user_id?: string;
    model_id?: string;
    provider_id?: string;
    start_date?: string;
    end_date?: string;
    skip?: number;
    limit?: number;
  }) {
    const res = await this.client.get('/costs/records', { params: toPageParams(params) });
    return res.data;
  }

  async getCostSummary(params?: {
    user_id?: string;
    start_date?: string;
    end_date?: string;
  }) {
    const res = await this.client.get('/costs/summary', { params });
    return res.data;
  }

  // Workflows
  async getWorkflows(params?: { limit?: number; status?: string }) {
    const res = await this.client.get('/workflows', { params: toPageParams(params) });
    return res.data;
  }

  async getWorkflow(id: string) {
    const res = await this.client.get(`/workflows/${id}`);
    return res.data;
  }

  async createWorkflow(data: { name: string; description?: string; definition: any }) {
    const res = await this.client.post('/workflows', data);
    return res.data;
  }

  async updateWorkflow(
    id: string,
    data: Partial<{ name: string; description: string; definition: any; status: string }>
  ) {
    const res = await this.client.patch(`/workflows/${id}`, data);
    return res.data;
  }

  async deleteWorkflow(id: string) {
    const res = await this.client.delete(`/workflows/${id}`);
    return res.data;
  }

  async validateWorkflowDefinition(definition: any) {
    const res = await this.client.post('/workflows/validate', definition);
    return res.data;
  }

  async executeWorkflow(id: string, data: { input_data: any; async_mode?: boolean }) {
    const res = await this.client.post(`/workflows/${id}/execute`, data);
    return res.data;
  }

  // 执行历史（含 node_executions 明细；分页 items 已被拦截器摊平）
  async getWorkflowExecutions(
    id: string,
    params?: { skip?: number; limit?: number; status?: string }
  ): Promise<WorkflowExecution[]> {
    const res = await this.client.get(`/workflows/${id}/executions`, { params: toPageParams(params) });
    return (res.data || []) as WorkflowExecution[];
  }

  // Notifications（网关信封里的分页 items 已被拦截器摊平成数组）
  async getNotifications(params?: { unread_only?: boolean; limit?: number }) {
    const query: Record<string, any> = toPageParams(params) ?? { page: 1, page_size: 20 };
    if (params?.unread_only) query.unread_only = true;
    const res = await this.client.get('/notifications', { params: query });
    return (res.data || []) as NotificationItem[];
  }

  async getUnreadNotificationCount(): Promise<number> {
    const res = await this.client.get('/notifications/unread-count');
    return res.data?.unread_count ?? 0;
  }

  async markNotificationRead(id: string) {
    const res = await this.client.patch(`/notifications/${id}/read`);
    return res.data as NotificationItem;
  }

  async markAllNotificationsRead() {
    const res = await this.client.patch('/notifications/read-all');
    return res.data;
  }

  async deleteNotification(id: string) {
    const res = await this.client.delete(`/notifications/${id}`);
    return res.data;
  }

  // Health
  async healthCheck() {
    const res = await this.client.get('/health');
    return res.data;
  }
}

export const api = new ApiClient();
