import axios, { AxiosError, AxiosInstance } from 'axios';
import { AuditLog, CostSummary, ModelConfig, Tenant, TokenBudget, UsageRecord, User } from '@/types';

// 默认走 same-origin 的 Next rewrite（/api/* -> http://localhost:8000/api/*），
// 这样浏览器端没有跨域问题；也可以在 .env.local 里覆盖成绝对地址。
const API_URL = process.env.NEXT_PUBLIC_API_URL || '/api/v1';

export class ApiError extends Error {
  code: string;
  status?: number;
  details?: Record<string, any>;

  constructor(message: string, code = 'UNKNOWN', status?: number, details?: Record<string, any>) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

const ACCESS_TOKEN_KEY = 'access_token';
const REFRESH_TOKEN_KEY = 'refresh_token';

function readToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(ACCESS_TOKEN_KEY);
}

interface RawUser {
  id: string;
  email: string;
  username?: string;
  display_name?: string;
  role: string;
  status?: string;
  is_active?: boolean;
  tenant_id: string;
  last_login_at?: string | null;
  created_at?: string;
  updated_at?: string;
}

interface RawModel {
  id: string;
  name: string;
  provider: string;
  capabilities?: string[];
  context_window: number;
  max_output_tokens: number;
  pricing?: Record<string, any>;
  parameters?: Record<string, any>;
  enabled: boolean;
}

function mapUser(u: RawUser): User {
  return {
    id: u.id,
    email: u.email,
    username: u.username,
    full_name: u.display_name || u.username || u.email,
    role: (u.role as User['role']) || 'MEMBER',
    is_active: u.is_active ?? (u.status ? u.status.toUpperCase() === 'ACTIVE' : true),
    tenant_id: u.tenant_id,
    last_login_at: u.last_login_at ?? null,
    created_at: u.created_at || new Date().toISOString(),
    updated_at: u.updated_at,
  };
}

function mapModel(m: RawModel): ModelConfig {
  return {
    id: m.id,
    provider: m.provider,
    name: m.name,
    capabilities: m.capabilities || [],
    context_window: m.context_window,
    max_output_tokens: m.max_output_tokens,
    pricing: m.pricing || {},
    enabled: m.enabled,
  };
}

class ApiClient {
  private client: AxiosInstance;

  constructor() {
    this.client = axios.create({
      baseURL: API_URL,
      headers: { 'Content-Type': 'application/json' },
      timeout: 60000,
    });

    this.client.interceptors.request.use((config) => {
      const token = readToken();
      if (token) config.headers.Authorization = `Bearer ${token}`;
      return config;
    });

    this.client.interceptors.response.use(
      (response) => response,
      (error: AxiosError<any>) => {
        const status = error.response?.status;
        const body = error.response?.data;
        const message =
          body?.error?.message ||
          (typeof body?.detail === 'string' ? body.detail : undefined) ||
          (Array.isArray(body?.detail) ? body.detail[0]?.msg : undefined) ||
          error.message ||
          '请求失败';

        // 令牌过期：清掉本地会话，让登录页重新接管
        if (status === 401 && typeof window !== 'undefined') {
          localStorage.removeItem(ACCESS_TOKEN_KEY);
          localStorage.removeItem(REFRESH_TOKEN_KEY);
        }
        return Promise.reject(new ApiError(message, body?.error?.code || 'HTTP_ERROR', status, body?.error?.details));
      }
    );
  }

  private unwrap<T>(body: any): T {
    if (body && typeof body === 'object' && 'data' in body) return body.data as T;
    return body as T;
  }

  private async get<T>(url: string, params?: Record<string, any>): Promise<T> {
    const res = await this.client.get(url, { params });
    return this.unwrap<T>(res.data);
  }

  private async post<T>(url: string, data?: any): Promise<T> {
    const res = await this.client.post(url, data);
    return this.unwrap<T>(res.data);
  }

  private async patch<T>(url: string, data?: any): Promise<T> {
    const res = await this.client.patch(url, data);
    return this.unwrap<T>(res.data);
  }

  private async del<T>(url: string): Promise<T> {
    const res = await this.client.delete(url);
    return this.unwrap<T>(res.data);
  }

  // ---------------------------------------------------------------- 认证
  async login(email: string, password: string): Promise<User> {
    const data = await this.post<{ access_token: string; refresh_token: string; user: RawUser }>(
      '/auth/login',
      { email, password, remember_me: true }
    );
    localStorage.setItem(ACCESS_TOKEN_KEY, data.access_token);
    if (data.refresh_token) localStorage.setItem(REFRESH_TOKEN_KEY, data.refresh_token);
    return mapUser(data.user);
  }

  async me(): Promise<User> {
    const data = await this.get<any>('/auth/me');
    return mapUser(data?.user || data);
  }

  async logout(): Promise<void> {
    try {
      await this.post('/auth/logout');
    } finally {
      localStorage.removeItem(ACCESS_TOKEN_KEY);
      localStorage.removeItem(REFRESH_TOKEN_KEY);
    }
  }

  hasSession(): boolean {
    return !!readToken();
  }

  // ---------------------------------------------------------------- 用户
  async getUsers(params?: { skip?: number; limit?: number }): Promise<User[]> {
    const pageSize = params?.limit ?? 100;
    const page = params?.skip ? Math.floor(params.skip / pageSize) + 1 : 1;
    const data = await this.get<{ items: RawUser[] }>('/users', { page, page_size: pageSize });
    return (data.items || []).map(mapUser);
  }

  async createUser(form: {
    email: string;
    full_name?: string;
    username?: string;
    password: string;
    role?: string;
    [key: string]: any;
  }): Promise<User> {
    const username =
      form.username ||
      form.email.split('@')[0].replace(/[^a-zA-Z0-9_-]/g, '').slice(0, 40) ||
      `user${Date.now() % 100000}`;
    const data = await this.post<RawUser>('/users', {
      email: form.email,
      username,
      password: form.password,
      display_name: form.full_name || username,
      role: form.role || 'MEMBER',
    });
    return mapUser(data);
  }

  async updateUser(
    id: string,
    form: { full_name?: string; role?: string; is_active?: boolean; [key: string]: any }
  ): Promise<User> {
    const data = await this.patch<RawUser>(`/users/${id}`, {
      display_name: form.full_name,
      role: form.role,
      status: form.is_active === undefined ? undefined : form.is_active ? 'ACTIVE' : 'INACTIVE',
    });
    return mapUser(data);
  }

  async deleteUser(id: string): Promise<void> {
    await this.del(`/users/${id}`);
  }

  // ---------------------------------------------------------------- 租户
  async getTenants(params?: { skip?: number; limit?: number }): Promise<Tenant[]> {
    const data = await this.get<Tenant[] | { items: Tenant[] }>('/tenants', {
      page: 1,
      page_size: params?.limit ?? 100,
    });
    // 网关对这个接口直接返回数组（没有分页包装），两种形态都兼容
    if (Array.isArray(data)) return data;
    return data?.items || [];
  }

  async createTenant(form: { name: string; slug?: string; [key: string]: any }): Promise<Tenant> {
    const slug =
      form.slug ||
      form.name
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-|-$/g, '')
        .slice(0, 40) ||
      `tenant-${Date.now() % 100000}`;
    return this.post<Tenant>('/tenants', { name: form.name, slug });
  }

  async updateTenant(
    id: string,
    form: { name?: string; settings?: Record<string, any>; [key: string]: any }
  ): Promise<Tenant> {
    return this.patch<Tenant>(`/tenants/${id}`, form);
  }

  // ---------------------------------------------------------------- 模型
  async getModels(params?: { limit?: number }): Promise<ModelConfig[]> {
    const data = await this.get<RawModel[]>('/models', { enabled_only: false });
    const models = (Array.isArray(data) ? data : []).map(mapModel);
    return params?.limit ? models.slice(0, params.limit) : models;
  }

  async updateModel(id: string, form: { enabled: boolean }): Promise<ModelConfig> {
    const data = await this.patch<RawModel>(`/models/${id}`, form);
    return mapModel(data);
  }

  // ---------------------------------------------------------------- 审计
  async getAuditLogs(params?: {
    skip?: number;
    limit?: number;
    action?: string;
    resource?: string;
    success?: boolean;
    start_date?: string;
    end_date?: string;
    [key: string]: any;
  }): Promise<AuditLog[]> {
    // 网关限制 page_size <= 100
    const pageSize = Math.min(params?.limit ?? 100, 100);
    const data = await this.get<{ items: AuditLog[] }>('/audit-logs', {
      page: params?.skip ? Math.floor(params.skip / pageSize) + 1 : 1,
      page_size: pageSize,
      action: params?.action || undefined,
      resource: params?.resource || undefined,
      success: params?.success,
      start_date: params?.start_date || undefined,
      end_date: params?.end_date || undefined,
    });
    return data.items || [];
  }

  // ---------------------------------------------------------------- 成本
  async getCostSummary(params?: { start_date?: string; end_date?: string }): Promise<CostSummary> {
    return this.get<CostSummary>('/costs/summary', params);
  }

  async getUsageRecords(params?: {
    skip?: number;
    limit?: number;
    start_date?: string;
    end_date?: string;
    [key: string]: any;
  }): Promise<UsageRecord[]> {
    const data = await this.get<{ items: UsageRecord[] }>('/costs/records', {
      page: 1,
      page_size: params?.limit ?? 100,
    });
    return data.items || [];
  }

  async getBudget(): Promise<TokenBudget> {
    return this.get<TokenBudget>('/costs/budget');
  }
}

export const api = new ApiClient();
