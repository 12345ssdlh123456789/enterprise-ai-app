'use client';

import { render, screen, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { AuthGate } from '@/components/auth-gate';
import { useAuth } from '@/lib/auth';

vi.mock('@/lib/auth', () => ({
  useAuth: vi.fn(),
  AuthProvider: ({ children }: any) => <div>{children}</div>,
}));

const mockedUseAuth = vi.mocked(useAuth);

function setAuth(overrides: Partial<ReturnType<typeof useAuth>>) {
  mockedUseAuth.mockReturnValue({
    user: null,
    tenant: null,
    isLoading: false,
    isAuthenticated: false,
    login: vi.fn(),
    logout: vi.fn(),
    ...overrides,
  } as ReturnType<typeof useAuth>);
}

const admin = {
  id: 'u1',
  email: 'admin@example.com',
  full_name: '管理员',
  role: 'ADMIN' as const,
  is_active: true,
  created_at: new Date().toISOString(),
};

describe('AuthGate', () => {
  beforeEach(() => {
    setAuth({});
  });

  afterEach(() => {
    cleanup();
  });

  it('加载中显示 role="status" 的占位，不闪登录表单', () => {
    setAuth({ isLoading: true });

    render(<AuthGate>内容</AuthGate>);

    expect(screen.getByRole('status')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '登录' })).not.toBeInTheDocument();
  });

  it('未登录时渲染登录表单（邮箱带默认演示账号）', () => {
    render(<AuthGate>内容</AuthGate>);

    expect(screen.getByLabelText('邮箱')).toHaveValue('admin@example.com');
    expect(screen.getByLabelText('密码')).toHaveAttribute('type', 'password');
    expect(screen.getByRole('button', { name: '登录' })).toBeInTheDocument();
  });

  it('登录失败时用 role="alert" 显示后端文案', async () => {
    const login = vi.fn().mockRejectedValue(new Error('该账号没有管理后台权限（需要管理员角色）'));
    setAuth({ login });

    render(<AuthGate>内容</AuthGate>);
    await userEvent.type(screen.getByLabelText('密码'), 'bad');
    await userEvent.click(screen.getByRole('button', { name: '登录' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('该账号没有管理后台权限（需要管理员角色）');
    expect(login).toHaveBeenCalledWith('admin@example.com', 'bad');
  });

  it('已登录时提供跳转主内容的链接和 <main id="main">', () => {
    setAuth({ user: admin, isAuthenticated: true });

    render(
      <AuthGate>
        <p>页面内容</p>
      </AuthGate>
    );

    expect(screen.getByRole('link', { name: '跳到主内容' })).toHaveAttribute('href', '#main');
    expect(screen.getByRole('main')).toHaveAttribute('id', 'main');
    expect(screen.getByText('页面内容')).toBeInTheDocument();
  });

  it('当前页导航带 aria-current="page"，其余不带', () => {
    setAuth({ user: admin, isAuthenticated: true });

    render(<AuthGate>内容</AuthGate>);

    const nav = screen.getByRole('navigation', { name: '主导航' });
    expect(nav).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /总览/ })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: /用户/ })).not.toHaveAttribute('aria-current');
  });

  it('退出按钮调用 logout', async () => {
    const logout = vi.fn().mockResolvedValue(undefined);
    setAuth({ user: admin, isAuthenticated: true, logout });

    render(<AuthGate>内容</AuthGate>);
    await userEvent.click(screen.getByRole('button', { name: /退出/ }));

    expect(logout).toHaveBeenCalledTimes(1);
  });
});
