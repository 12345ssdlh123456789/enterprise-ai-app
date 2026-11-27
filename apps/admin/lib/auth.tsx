'use client';

import { createContext, useContext, useEffect, useState, ReactNode, useCallback } from 'react';
import { api } from '@/lib/api';
import { Tenant, User } from '@/types';

interface AuthContextType {
  user: User | null;
  tenant: Tenant | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const init = useCallback(async () => {
    if (!api.hasSession()) {
      setIsLoading(false);
      return;
    }
    try {
      setUser(await api.me());
    } catch {
      // token 过期或后端没起来：退回登录页
      setUser(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    init();
  }, [init]);

  const login = async (email: string, password: string) => {
    const u = await api.login(email, password);
    if (u.role !== 'ADMIN' && u.role !== 'SUPER_ADMIN') {
      await api.logout();
      throw new Error('该账号没有管理后台权限（需要管理员角色）');
    }
    setUser(u);
  };

  const logout = async () => {
    try {
      await api.logout();
    } catch {
      // 后端不可达 / 500（本地 SQLite 并发写锁就会这样）时也要结束本地会话：
      // api.logout 在 finally 里已经删掉 token，这里再不清 user 就会留下
      // 「界面显示已登录、后续请求全 401」的半坏状态。
    } finally {
      setUser(null);
      setTenant(null);
    }
  };

  return (
    <AuthContext.Provider
      value={{ user, tenant, isLoading, isAuthenticated: !!user, login, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
