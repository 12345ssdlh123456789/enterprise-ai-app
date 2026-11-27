import '@testing-library/jest-dom';
import { vi } from 'vitest';

// next/link 在 jsdom 里需要 app router 上下文，测试里换成普通 <a>。
vi.mock('next/link', () => ({
  default: ({ href, children, ...props }: any) => (
    <a href={typeof href === 'string' ? href : '#'} {...props}>
      {children}
    </a>
  ),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
  }),
  usePathname: () => '/',
  useSearchParams: () => new URLSearchParams(),
}));

// 组件测试默认是「已登录管理员」；需要别的状态时在用例里重新 mock。
vi.mock('@/lib/auth', () => ({
  useAuth: () => ({
    user: {
      id: 'u1',
      email: 'admin@example.com',
      full_name: '管理员',
      role: 'ADMIN',
      is_active: true,
      created_at: new Date().toISOString(),
    },
    tenant: { id: 't1', name: '演示租户', slug: 'demo', settings: {} },
    isLoading: false,
    isAuthenticated: true,
    login: vi.fn(),
    logout: vi.fn(),
  }),
  AuthProvider: ({ children }: any) => <div>{children}</div>,
}));

// 组件测试不应真的发请求；请求层用例会 vi.unmock('@/lib/api')。
vi.mock('@/lib/api', () => ({
  ApiError: class ApiError extends Error {},
  api: {
    hasSession: vi.fn().mockReturnValue(false),
    me: vi.fn(),
    login: vi.fn(),
    logout: vi.fn().mockResolvedValue(undefined),
    getUsers: vi.fn().mockResolvedValue([]),
    getTenants: vi.fn().mockResolvedValue([]),
    getModels: vi.fn().mockResolvedValue([]),
    getAuditLogs: vi.fn().mockResolvedValue([]),
    getCostSummary: vi.fn().mockResolvedValue({ total_cost: 0, total_tokens: 0 }),
    getUsageRecords: vi.fn().mockResolvedValue([]),
    getBudget: vi.fn().mockResolvedValue({ limit: 0, used: 0, usage_percentage: 0 }),
  },
}));

if (!window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }),
  });
}
