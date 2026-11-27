/**
 * lib/auth.tsx（AuthProvider）单元测试。
 *
 * setup.tsx 全局把 `@/lib/auth` 和 `next/navigation` 都 mock 掉了，这里分别
 * unmock / 重新 mock，测的是真实的 AuthProvider：initAuth、刷新、登录、登出。
 * 网络层用可编程的 fetch 替身，不启动后端。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, waitFor } from '@testing-library/react';

const nav = vi.hoisted(() => ({ push: vi.fn() }));

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: nav.push,
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
    refresh: vi.fn(),
  }),
}));

vi.unmock('@/lib/auth');

import { AuthProvider, useAuth } from '@/lib/auth';

const API_URL = 'http://127.0.0.1:8000/api/v1';

const jsonOk = (body: any) => ({ ok: true, status: 200, json: async () => body }) as Response;
const jsonError = (body: any, status = 400) =>
  ({ ok: false, status, json: async () => body }) as unknown as Response;

let ctx: any;

function Probe() {
  ctx = useAuth();
  return <div data-testid="user">{ctx.user?.email ?? 'anon'}</div>;
}

function renderProvider() {
  return render(
    <AuthProvider>
      <Probe />
    </AuthProvider>
  );
}

const fetchMock = vi.fn();

beforeEach(() => {
  localStorage.clear();
  nav.push.mockReset();
  fetchMock.mockReset();
  global.fetch = fetchMock as any;
  ctx = undefined;
});

describe('AuthProvider', () => {
  it('没有本地 token 时不去拉 /auth/me，直接结束 loading', async () => {
    renderProvider();

    await waitFor(() => expect(ctx?.isLoading).toBe(false));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(ctx.user).toBeNull();
  });

  it('有 token 时用 Bearer 头拉 /auth/me，并解包信封设置 user / tenant', async () => {
    localStorage.setItem('access_token', 'tok-1');
    fetchMock.mockResolvedValue(
      jsonOk({
        success: true,
        data: {
          id: 'u1',
          email: 'admin@example.com',
          full_name: '管理员',
          role: 'ADMIN',
          is_active: true,
          created_at: '2026-11-01T00:00:00Z',
          tenant: { id: 't1', name: 'Demo Tenant', slug: 'demo', settings: {} },
        },
      })
    );

    renderProvider();

    await waitFor(() => expect(ctx?.isLoading).toBe(false));
    expect(ctx.user.email).toBe('admin@example.com');
    expect(ctx.tenant.slug).toBe('demo');

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe(`${API_URL}/auth/me`);
    expect((init as any).headers.Authorization).toBe('Bearer tok-1');
  });

  it('/auth/me 失败但有 refresh_token 时，先刷新再重新取用户', async () => {
    localStorage.setItem('access_token', 'stale');
    localStorage.setItem('refresh_token', 'refresh-1');

    fetchMock.mockImplementation(async (url: string, init?: any) => {
      if (url.endsWith('/auth/me')) {
        const auth = (init?.headers || {}).Authorization;
        if (auth === 'Bearer stale') return jsonError({ detail: 'invalid token' }, 401);
        return jsonOk({ data: { id: 'u1', email: 'fresh@example.com', role: 'MEMBER' } });
      }
      if (url.endsWith('/auth/refresh')) {
        return jsonOk({ data: { access_token: 'fresh', refresh_token: 'refresh-2' } });
      }
      throw new Error(`unexpected fetch: ${url}`);
    });

    renderProvider();

    await waitFor(() => expect(ctx?.isLoading).toBe(false));
    expect(ctx.user.email).toBe('fresh@example.com');
    expect(localStorage.getItem('access_token')).toBe('fresh');
    expect(localStorage.getItem('refresh_token')).toBe('refresh-2');
  });

  it('刷新也失败时清掉本地 token，用户保持未登录', async () => {
    localStorage.setItem('access_token', 'stale');
    localStorage.setItem('refresh_token', 'bad-refresh');

    fetchMock.mockImplementation(async (url: string) => {
      if (url.endsWith('/auth/me')) return jsonError({ detail: 'invalid token' }, 401);
      if (url.endsWith('/auth/refresh')) return jsonError({ detail: 'refresh expired' }, 401);
      throw new Error(`unexpected fetch: ${url}`);
    });

    renderProvider();

    await waitFor(() => expect(ctx?.isLoading).toBe(false));
    expect(ctx.user).toBeNull();
    expect(localStorage.getItem('access_token')).toBeNull();
    expect(localStorage.getItem('refresh_token')).toBeNull();
  });

  it('登录成功后保存双 token、拉取用户并跳回首页', async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url.endsWith('/auth/login')) {
        return jsonOk({ data: { access_token: 'a-token', refresh_token: 'r-token' } });
      }
      if (url.endsWith('/auth/me')) {
        return jsonOk({ data: { id: 'u1', email: 'admin@example.com', role: 'ADMIN' } });
      }
      throw new Error(`unexpected fetch: ${url}`);
    });

    renderProvider();
    await waitFor(() => expect(ctx?.isLoading).toBe(false));

    await ctx.login('admin@example.com', 'admin123');

    expect(localStorage.getItem('access_token')).toBe('a-token');
    expect(localStorage.getItem('refresh_token')).toBe('r-token');
    expect(nav.push).toHaveBeenCalledWith('/');
    await waitFor(() => expect(ctx.user.email).toBe('admin@example.com'));
  });

  it('登录失败时抛出后端给的 detail 文案，且不写任何 token', async () => {
    fetchMock.mockImplementation(async (url: string) => {
      if (url.endsWith('/auth/login')) return jsonError({ detail: '邮箱或密码错误' }, 401);
      throw new Error(`unexpected fetch: ${url}`);
    });

    renderProvider();
    await waitFor(() => expect(ctx?.isLoading).toBe(false));

    await expect(ctx.login('admin@example.com', 'wrong')).rejects.toThrow('邮箱或密码错误');
    expect(localStorage.getItem('access_token')).toBeNull();
    expect(nav.push).not.toHaveBeenCalled();
  });

  it('登出会调用后端并清空本地身份', async () => {
    localStorage.setItem('access_token', 'tok-1');
    fetchMock.mockImplementation(async (url: string) => {
      if (url.endsWith('/auth/me')) return jsonOk({ data: { id: 'u1', email: 'admin@example.com' } });
      if (url.endsWith('/auth/logout')) return jsonOk({ success: true });
      throw new Error(`unexpected fetch: ${url}`);
    });

    renderProvider();
    await waitFor(() => expect(ctx?.user?.email).toBe('admin@example.com'));

    await ctx.logout();

    expect(localStorage.getItem('access_token')).toBeNull();
    await waitFor(() => expect(ctx.user).toBeNull());
    expect(ctx.isAuthenticated).toBe(false);
    const logoutCall = fetchMock.mock.calls.find(([u]) => String(u).endsWith('/auth/logout'));
    expect(logoutCall).toBeTruthy();
  });
});
