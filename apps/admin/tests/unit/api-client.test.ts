/**
 * 管理后台请求层（lib/api.ts）单元测试。
 *
 * setup.ts 默认 mock 了 `@/lib/api`，这里必须 `vi.unmock` 才能测真实实现。
 * axios 用可编程替身，但真的执行 api.ts 注册的拦截器，
 * 所以「带 Bearer token / 解包网关信封 / 401 清会话 / 错误文案映射」都是真跑的。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const fake = vi.hoisted(() => ({
  adapter: (async () => ({ data: {}, status: 200, headers: {}, config: {} })) as (config: any) => Promise<any>,
  requestInterceptors: [] as Array<(config: any) => any>,
  responseInterceptors: [] as Array<[((r: any) => any) | undefined, ((e: any) => any) | undefined]>,
  calls: [] as any[],
}));

vi.mock('axios', () => {
  const run = async (method: string, url: string, data?: any, config: any = {}) => {
    let cfg: any = { ...config, method, url, data };
    cfg.headers = { ...(config.headers || {}) };

    for (const onRequest of fake.requestInterceptors) {
      cfg = (await onRequest(cfg)) || cfg;
    }

    fake.calls.push(cfg);

    let response: any;
    try {
      response = await fake.adapter(cfg);
    } catch (thrown: any) {
      const error = thrown instanceof Error ? thrown : Object.assign(new Error('request failed'), thrown);
      if (!(error as any).config) (error as any).config = cfg;
      for (const [, onRejected] of fake.responseInterceptors) {
        if (onRejected) return await onRejected(error);
      }
      throw error;
    }

    for (const [onFulfilled] of fake.responseInterceptors) {
      if (onFulfilled) response = (await onFulfilled(response)) || response;
    }
    return response;
  };

  const client: any = (config: any) => run(config?.method || 'get', config?.url, config?.data, config);
  client.defaults = {};
  client.request = (config: any) => client(config);
  client.get = (url: string, config?: any) => run('get', url, undefined, config);
  client.post = (url: string, data?: any, config?: any) => run('post', url, data, config);
  client.patch = (url: string, data?: any, config?: any) => run('patch', url, data, config);
  client.delete = (url: string, config?: any) => run('delete', url, undefined, config);
  client.interceptors = {
    request: {
      use: (fn: (config: any) => any) => {
        fake.requestInterceptors.push(fn);
      },
    },
    response: {
      use: (onFulfilled?: any, onRejected?: any) => {
        fake.responseInterceptors.push([onFulfilled, onRejected]);
      },
    },
  };

  const axios: any = { create: () => client };
  return { default: axios, ...axios };
});

vi.unmock('@/lib/api');

import { api, ApiError } from '@/lib/api';

const ok = (data: any) => ({ data, status: 200, headers: {}, config: {} });
const statusError = (status: number, body: any = {}) =>
  Object.assign(new Error(`Request failed with status code ${status}`), {
    response: { status, data: body },
  });

describe('admin lib/api 请求层', () => {
  beforeEach(() => {
    localStorage.clear();
    fake.calls = [];
    fake.adapter = async () => ok({});
  });

  it('有 token 时带上 Authorization 头', async () => {
    localStorage.setItem('access_token', 'tok-1');
    let seen: any;
    fake.adapter = async (cfg) => {
      seen = cfg;
      return ok({});
    };

    await api.me();

    expect(seen.headers.Authorization).toBe('Bearer tok-1');
  });

  it('没有 token 时不发 Authorization 头', async () => {
    let seen: any;
    fake.adapter = async (cfg) => {
      seen = cfg;
      return ok({});
    };

    await api.me();

    expect(seen.headers.Authorization).toBeUndefined();
  });

  it('解包 { success, data } 信封', async () => {
    fake.adapter = async () =>
      ok({
        success: true,
        data: {
          items: [
            {
              id: 'u1',
              email: 'a@example.com',
              display_name: '张三',
              role: 'ADMIN',
              status: 'ACTIVE',
              tenant_id: 't1',
            },
          ],
        },
      });

    const users = await api.getUsers();

    expect(users).toHaveLength(1);
    expect(users[0]).toMatchObject({
      id: 'u1',
      full_name: '张三',
      role: 'ADMIN',
      is_active: true,
    });
  });

  it('非信封响应原样返回', async () => {
    fake.adapter = async () => ok([{ id: 't1', name: '租户', slug: 't1', settings: {} }]);

    await expect(api.getTenants()).resolves.toHaveLength(1);
  });

  it('getTenants 同时兼容数组和 { items } 两种形态', async () => {
    fake.adapter = async () => ok({ items: [{ id: 't2', name: 'B', slug: 'b', settings: {} }] });

    const tenants = await api.getTenants();

    expect(tenants.map((t) => t.id)).toEqual(['t2']);
  });

  it('skip/limit 转成后端 page/page_size', async () => {
    let params: any;
    fake.adapter = async (cfg) => {
      params = cfg.params;
      return ok({ items: [] });
    };

    await api.getUsers({ skip: 40, limit: 20 });

    expect(params).toMatchObject({ page: 3, page_size: 20 });
  });

  it('getAuditLogs 把 page_size 限制在 100（网关上限）', async () => {
    let params: any;
    fake.adapter = async (cfg) => {
      params = cfg.params;
      return ok({ items: [] });
    };

    await api.getAuditLogs({ limit: 500 });

    expect(params.page_size).toBe(100);
  });

  it('status=INACTIVE 映射成 is_active=false', async () => {
    fake.adapter = async () =>
      ok({ id: 'u2', email: 'b@example.com', role: 'MEMBER', status: 'INACTIVE', tenant_id: 't1' });

    const user = await api.me();

    expect(user.is_active).toBe(false);
  });

  it('后端 error.message 映射成 ApiError.message', async () => {
    fake.adapter = async () => {
      throw statusError(403, { error: { message: '没有权限', code: 'FORBIDDEN' } });
    };

    await expect(api.getUsers()).rejects.toMatchObject({
      name: 'ApiError',
      message: '没有权限',
      code: 'FORBIDDEN',
      status: 403,
    });
  });

  it('FastAPI 的 detail 字符串 / 校验数组都能变成可读文案', async () => {
    fake.adapter = async () => {
      throw statusError(400, { detail: '邮箱已存在' });
    };
    await expect(api.getUsers()).rejects.toMatchObject({ message: '邮箱已存在', status: 400 });

    fake.adapter = async () => {
      throw statusError(422, { detail: [{ msg: '字段必填' }] });
    };
    await expect(api.getUsers()).rejects.toMatchObject({ message: '字段必填', status: 422 });
  });

  it('401 时清掉本地 token 并抛出 ApiError', async () => {
    localStorage.setItem('access_token', 'expired');
    localStorage.setItem('refresh_token', 'r1');
    fake.adapter = async () => {
      throw statusError(401, {});
    };

    await expect(api.getUsers()).rejects.toBeInstanceOf(ApiError);

    expect(localStorage.getItem('access_token')).toBeNull();
    expect(localStorage.getItem('refresh_token')).toBeNull();
  });

  it('登录成功后写入 token 并返回映射后的用户', async () => {
    fake.adapter = async (cfg) => {
      expect(cfg.url).toBe('/auth/login');
      expect(cfg.data).toMatchObject({ email: 'admin@example.com', password: 'admin123' });
      return ok({
        access_token: 'access-1',
        refresh_token: 'refresh-1',
        user: {
          id: 'u1',
          email: 'admin@example.com',
          display_name: '管理员',
          role: 'SUPER_ADMIN',
          status: 'ACTIVE',
          tenant_id: 't1',
        },
      });
    };

    const user = await api.login('admin@example.com', 'admin123');

    expect(user).toMatchObject({ id: 'u1', full_name: '管理员', role: 'SUPER_ADMIN' });
    expect(localStorage.getItem('access_token')).toBe('access-1');
    expect(localStorage.getItem('refresh_token')).toBe('refresh-1');
  });

  it('登出接口失败也清掉本地 token', async () => {
    localStorage.setItem('access_token', 'a');
    localStorage.setItem('refresh_token', 'r');
    fake.adapter = async () => {
      throw statusError(500, {});
    };

    await expect(api.logout()).rejects.toBeTruthy();

    expect(localStorage.getItem('access_token')).toBeNull();
    expect(localStorage.getItem('refresh_token')).toBeNull();
  });

  it('hasSession 只看本地是否有 access_token', () => {
    expect(api.hasSession()).toBe(false);
    localStorage.setItem('access_token', 'a');
    expect(api.hasSession()).toBe(true);
  });
});
