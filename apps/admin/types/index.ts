export interface User {
  id: string;
  email: string;
  username?: string;
  full_name: string;
  role: 'SUPER_ADMIN' | 'ADMIN' | 'MEMBER' | 'VIEWER';
  is_active: boolean;
  tenant_id?: string;
  last_login_at?: string | null;
  created_at: string;
  updated_at?: string;
}

export interface Tenant {
  id: string;
  name: string;
  slug: string;
  plan?: string;
  settings: Record<string, any>;
  created_at: string;
  updated_at?: string;
}

export interface ModelConfig {
  id: string;
  provider: string;
  name: string;
  capabilities: string[];
  context_window: number;
  max_output_tokens: number;
  enabled: boolean;
  pricing: Record<string, any>;
}

export interface AuditLog {
  id: string;
  tenant_id: string;
  user_id: string | null;
  action: string;
  resource: string;
  resource_id: string | null;
  old_value?: Record<string, any> | null;
  new_value?: Record<string, any> | null;
  ip_address: string | null;
  user_agent: string | null;
  success: boolean;
  error_message: string | null;
  created_at: string;
}

export interface UsageRecord {
  id: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost: number;
  created_at: string;
  [key: string]: any;
}

export interface CostSummary {
  total_cost: number;
  total_tokens: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  by_model?: Record<string, number>;
  currency?: string;
  period_start?: string;
  period_end?: string;
  [key: string]: any;
}

export interface TokenBudget {
  tenant_id?: string;
  period?: string;
  limit: number;
  used: number;
  usage_percentage: number;
  reset_at?: string;
  [key: string]: any;
}

export interface ApiError {
  code: string;
  message: string;
  details?: Record<string, any>;
}
