/**
 * lib/api.ts 请求层单元测试。
 *
 * 注意：tests/unit/setup.tsx 全局 mock 了 `@/lib/api`（为了让组件测试不真的发请求），
 * 这里必须 `vi.unmock` 才能测到真实实现——否则测的是替身，等于没测。
 *
 * axios 用一个可编程替身：它真的执行 api.ts 注册的拦截器，
 * 所以「附带 Bearer token / 解包网关信封 / 401 自动刷新并重放」这些逻辑是被真实执行的。
 */
import { describe, it, expect, beforeEach, afterAll, vi } from 'vitest';

const fake = vi.hoisted(() => ({
  adapter: (async () => ({ data: {}, status: 200, headers: {}, config: {} })) as (config: any) => Promise<any>,
  requestInterceptors: [] as Array<(config: any) => any>,
  responseInterceptors: [] as Array<[((r: any) => any) | undefined, ((e: any) => any) | undefined]>,
  refreshPost: undefined as any,
  adapterCalls: [] as any[],
}));

vi.mock('axios', () => {
  // api.ts 重放请求时直接调用实例：`this.client(originalRequest)`，所以替身本身必须是函数
  let run: (method: string, url: string, data?: any, config?: any) => Promise<any>;

  const client: any = (config: any) => run(config?.method || 'get', config?.url, config?.data, config);
  client.defaults = {};

  run = async (method: string, url: string, data?: any, config: any = {}) => {
    let cfg: any = { ...config, method, url, data };
    cfg.headers = { ...(config.headers || {}) };

    for (const onRequest of fake.requestInterceptors) {
      cfg = (await onRequest(cfg)) || cfg;
    }

    fake.adapterCalls.push(cfg);

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

  const axios: any = {
    create: () => client,
    post: (...args: any[]) => fake.refreshPost(...args),
  };

  return { default: axios, ...axios };
});

vi.unmock('@/lib/api');

import { api } from '@/lib/api';

const ok = (data: any) => ({ data, status: 200, headers: {}, config: {} });
const statusError = (status: number) =>
  Object.assign(new Error(`Request failed with status code ${status}`), { response: { status, data: {} } });

describe('lib/api 请求层', () => {
  const originalLocation = window.location;

  beforeEach(() => {
    localStorage.clear();
    fake.adapterCalls = [];
    fake.adapter = async () => ok({});
    fake.refreshPost = vi.fn();
    Object.defineProperty(window, 'location', {
      writable: true,
      configurable: true,
      value: { ...originalLocation, href: 'http://localhost/' },
    });
  });

  afterAll(() => {
    Object.defineProperty(window, 'location', {
      writable: true,
      configurable: true,
      value: originalLocation,
    });
  });

  it('请求头自动带上 localStorage 里的 access_token', async () => {
    localStorage.setItem('access_token', 'tok-1');
    let seen: any;
    fake.adapter = async (cfg) => {
      seen = cfg;
      return ok({ id: 'u1' });
    };

    await api.getMe();

    expect(seen.headers.Authorization).toBe('Bearer tok-1');
  });

  it('没有 token 时不发 Authorization 头（不能发 "Bearer null"）', async () => {
    let seen: any;
    fake.adapter = async (cfg) => {
      seen = cfg;
      return ok({});
    };

    await api.getMe();

    expect(seen.headers.Authorization).toBeUndefined();
  });

  it('解包网关信封 { success, data } 并取出分页 items', async () => {
    fake.adapter = async () => ok({ success: true, data: { items: [{ id: 1 }, { id: 2 }], total: 2 }, error: null });

    const users = await api.getUsers();

    expect(users).toEqual([{ id: 1 }, { id: 2 }]);
  });

  it('非信封响应原样返回（健康检查这类裸对象）', async () => {
    fake.adapter = async () => ok({ status: 'healthy' });

    await expect(api.healthCheck()).resolves.toEqual({ status: 'healthy' });
  });

  it('skip/limit 转成后端的 page/page_size（否则 limit 被忽略）', async () => {
    let params: any;
    fake.adapter = async (cfg) => {
      params = cfg.params;
      return ok({ success: true, data: [] });
    };

    await api.getUsers({ skip: 40, limit: 20 });

    expect(params).toMatchObject({ page: 3, page_size: 20 });
  });

  it('401 时先刷新 token，再用新 token 重放一次原请求', async () => {
    localStorage.setItem('access_token', 'old-token');
    localStorage.setItem('refresh_token', 'refresh-1');
    fake.refreshPost = vi.fn().mockResolvedValue({ data: { access_token: 'new-token' } });

    fake.adapter = async (cfg) => {
      if (cfg.headers.Authorization === 'Bearer old-token') throw statusError(401);
      return ok({ success: true, data: { id: 'u1' } });
    };

    const me = await api.getMe();

    expect(me).toEqual({ id: 'u1' });
    expect(fake.adapterCalls).toHaveLength(2);
    expect(fake.adapterCalls[1].headers.Authorization).toBe('Bearer new-token');
    expect(fake.refreshPost).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem('access_token')).toBe('new-token');
  });

  it('并发 401 只刷新一次（refreshPromise 去重）', async () => {
    localStorage.setItem('access_token', 'old-token');
    localStorage.setItem('refresh_token', 'refresh-1');

    let releaseRefresh: (value: any) => void = () => {};
    fake.refreshPost = vi.fn().mockReturnValue(
      new Promise((resolve) => {
        releaseRefresh = resolve;
      })
    );

    fake.adapter = async (cfg) => {
      if (cfg.headers.Authorization === 'Bearer old-token') throw statusError(401);
      return ok({ ok: true, url: cfg.url });
    };

    const first = api.getMe();
    const second = api.getUser('u2');
    await vi.waitFor(() => expect(fake.refreshPost).toHaveBeenCalled());
    releaseRefresh({ data: { access_token: 'new-token' } });

    await expect(first).resolves.toBeTruthy();
    await expect(second).resolves.toBeTruthy();
    expect(fake.refreshPost).toHaveBeenCalledTimes(1);
  });

  it('刷新失败时清掉本地 token 并回到首页', async () => {
    localStorage.setItem('access_token', 'old-token');
    localStorage.setItem('refresh_token', 'refresh-1');
    fake.refreshPost = vi.fn().mockRejectedValue(new Error('refresh denied'));
    fake.adapter = async () => {
      throw statusError(401);
    };

    await expect(api.getMe()).rejects.toBeTruthy();

    expect(localStorage.getItem('access_token')).toBeNull();
    expect(localStorage.getItem('refresh_token')).toBeNull();
    expect(window.location.href).toBe('/');
  });

  it('没有 refresh_token 时不尝试刷新，直接把 401 抛给调用方', async () => {
    localStorage.setItem('access_token', 'old-token');
    fake.adapter = async () => {
      throw statusError(401);
    };

    await expect(api.getMe()).rejects.toBeTruthy();
    expect(fake.refreshPost).not.toHaveBeenCalled();
  });

  it('getDocuments 把后端字段映射成前端 Document（file_name→filename 等）', async () => {
    fake.adapter = async () =>
      ok({
        success: true,
        data: {
          items: [
            {
              id: 'd1',
              title: '员工手册.pdf',
              file_name: 'handbook.pdf',
              mime_type: 'application/pdf',
              file_size: 1024,
              status: 'READY',
              metadata: { file_hash: 'abc' },
              chunk_count: 3,
            },
          ],
        },
      });

    const [doc] = await api.getDocuments('kb-1');

    expect(doc).toMatchObject({
      id: 'd1',
      filename: 'handbook.pdf',
      original_filename: '员工手册.pdf',
      content_type: 'application/pdf',
      file_size: 1024,
      file_hash: 'abc',
      status: 'ready',
      chunk_count: 3,
      token_count: 0,
      knowledge_base_id: 'kb-1',
    });
  });

  it('getNotifications 传 page/page_size，unread_only 只在需要时带', async () => {
    let seen: any;
    fake.adapter = async (cfg) => {
      seen = cfg;
      return ok({ success: true, data: { items: [{ id: 'n1' }], total: 1 } });
    };

    const list = await api.getNotifications({ limit: 50 });

    expect(seen.url).toBe('/notifications');
    expect(seen.params).toMatchObject({ page: 1, page_size: 50 });
    expect(seen.params.unread_only).toBeUndefined();
    expect(list).toEqual([{ id: 'n1' }]);

    await api.getNotifications({ unread_only: true, limit: 6 });
    expect(seen.params).toMatchObject({ page_size: 6, unread_only: true });
  });

  it('getUnreadNotificationCount 解包 unread_count', async () => {
    fake.adapter = async () => ok({ success: true, data: { unread_count: 3 }, error: null });

    await expect(api.getUnreadNotificationCount()).resolves.toBe(3);
  });

  it('标记已读用 PATCH /notifications/{id}/read', async () => {
    let seen: any;
    fake.adapter = async (cfg) => {
      seen = cfg;
      return ok({ success: true, data: { id: 'n1', read: true } });
    };

    const updated = await api.markNotificationRead('n1');

    expect(seen.method).toBe('patch');
    expect(seen.url).toBe('/notifications/n1/read');
    expect(updated).toMatchObject({ id: 'n1', read: true });
  });

  it('getWorkflowExecutions 走 /workflows/{id}/executions 并摊平分页 items', async () => {
    let seen: any;
    fake.adapter = async (cfg) => {
      seen = cfg;
      return ok({
        success: true,
        data: {
          items: [
            {
              id: 'e1',
              status: 'COMPLETED',
              node_executions: [{ node_id: 'start', status: 'completed', duration_ms: 1 }],
            },
          ],
          total: 1,
        },
      });
    };

    const list = await api.getWorkflowExecutions('wf-1', { limit: 50, status: 'COMPLETED' });

    expect(seen.method).toBe('get');
    expect(seen.url).toBe('/workflows/wf-1/executions');
    expect(seen.params).toMatchObject({ page: 1, page_size: 50, status: 'COMPLETED' });
    expect(list).toHaveLength(1);
    expect(list[0].node_executions[0].node_id).toBe('start');
  });

  it('getWorkflowExecutions 不传 status 时不带该参数', async () => {
    let seen: any;
    fake.adapter = async (cfg) => {
      seen = cfg;
      return ok({ success: true, data: { items: [], total: 0 } });
    };

    await expect(api.getWorkflowExecutions('wf-2')).resolves.toEqual([]);
    expect(seen.params.status).toBeUndefined();
  });

  it('全部已读与删除走对应端点', async () => {
    const calls: any[] = [];
    fake.adapter = async (cfg) => {
      calls.push(cfg);
      return ok({ success: true, data: {} });
    };

    await api.markAllNotificationsRead();
    await api.deleteNotification('n9');

    expect(calls[0].method).toBe('patch');
    expect(calls[0].url).toBe('/notifications/read-all');
    expect(calls[1].method).toBe('delete');
    expect(calls[1].url).toBe('/notifications/n9');
  });
});
