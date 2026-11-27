/**
 * lib/auth.tsx（AuthProvider）单元测试 —— 管理后台的登录 / 登出状态机。
 *
 * setup.tsx 全局 mock 了 `@/lib/auth` 与 `@/lib/api`：这里 unmock auth，
 * 并把请求层换成可编程替身，测真实的 AuthProvider 逻辑（不启动后端）。
 */
import { render, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.unmock('@/lib/auth');

vi.mock('@/lib/api', () => ({
  ApiError: class ApiError extends Error {},
  api: {
    hasSession: vi.fn(),
    me: vi.fn(),
    login: vi.fn(),
    logout: vi.fn(),
  },
}));

import { AuthProvider, useAuth } from '@/lib/auth';
import { api } from '@/lib/api';

const admin = {
  id: 'u1',
  email: 'admin@example.com',
  full_name: '管理员',
  role: 'ADMIN' as const,
  is_active: true,
  created_at: '2026-11-01T00:00:00Z',
};

let ctx: ReturnType<typeof useAuth> | undefined;

function Probe() {
  ctx = useAuth();
  return <div>{ctx.user?.email ?? 'anon'}</div>;
}

function renderProvider() {
  return render(
    <AuthProvider>
      <Probe />
    </AuthProvider>
  );
}

beforeEach(() => {
  ctx = undefined;
  vi.mocked(api.hasSession).mockReset().mockReturnValue(false);
  vi.mocked(api.me).mockReset();
  vi.mocked(api.login).mockReset();
  vi.mocked(api.logout).mockReset().mockResolvedValue(undefined);
});

describe('AuthProvider', () => {
  it('没有本地会话时不去拉 /auth/me，直接结束 loading', async () => {
    renderProvider();

    await waitFor(() => expect(ctx?.isLoading).toBe(false));
    expect(api.me).not.toHaveBeenCalled();
    expect(ctx?.user).toBeNull();
    expect(ctx?.isAuthenticated).toBe(false);
  });

  it('有本地会话时用 me() 恢复用户', async () => {
    vi.mocked(api.hasSession).mockReturnValue(true);
    vi.mocked(api.me).mockResolvedValue(admin);

    renderProvider();

    await waitFor(() => expect(ctx?.isLoading).toBe(false));
    expect(ctx?.user?.email).toBe('admin@example.com');
    expect(ctx?.isAuthenticated).toBe(true);
  });

  it('me() 失败（token 过期 / 后端没起）退回未登录，不抛错', async () => {
    vi.mocked(api.hasSession).mockReturnValue(true);
    vi.mocked(api.me).mockRejectedValue(new Error('401'));

    renderProvider();

    await waitFor(() => expect(ctx?.isLoading).toBe(false));
    expect(ctx?.user).toBeNull();
    expect(ctx?.isAuthenticated).toBe(false);
  });

  it('非管理员账号登录被拒，并撤销刚拿到的会话', async () => {
    vi.mocked(api.login).mockResolvedValue({ ...admin, role: 'VIEWER' });

    renderProvider();
    await waitFor(() => expect(ctx?.isLoading).toBe(false));

    await expect(ctx!.login('viewer@example.com', 'viewer123')).rejects.toThrow('管理员');
    expect(api.logout).toHaveBeenCalled();
    expect(ctx?.user).toBeNull();
  });

  it('登出时后端报错也要清空本地身份（否则界面已登录、请求全 401）', async () => {
    vi.mocked(api.hasSession).mockReturnValue(true);
    vi.mocked(api.me).mockResolvedValue(admin);
    vi.mocked(api.logout).mockRejectedValue(new Error('database is locked'));

    renderProvider();
    await waitFor(() => expect(ctx?.user?.email).toBe('admin@example.com'));

    await ctx!.logout();

    await waitFor(() => expect(ctx?.user).toBeNull());
    expect(ctx?.tenant).toBeNull();
    expect(ctx?.isAuthenticated).toBe(false);
  });

  it('正常登出清空身份并调用后端', async () => {
    vi.mocked(api.hasSession).mockReturnValue(true);
    vi.mocked(api.me).mockResolvedValue(admin);

    renderProvider();
    await waitFor(() => expect(ctx?.user?.email).toBe('admin@example.com'));

    await ctx!.logout();

    expect(api.logout).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(ctx?.user).toBeNull());
  });
});
