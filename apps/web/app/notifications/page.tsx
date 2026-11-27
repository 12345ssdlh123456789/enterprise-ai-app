'use client';

import { useCallback, useEffect, useState } from 'react';
import { Bell, CheckCheck, Loader2, RefreshCw, Trash2 } from 'lucide-react';

import { useAuth } from '@/lib/auth';
import { api } from '@/lib/api';
import { cn, formatRelativeTime } from '@/lib/utils';
import { NotificationItem } from '@/types';
import { Button } from '@/components/ui/button';

const TYPE_LABEL: Record<string, string> = {
  INFO: '通知',
  SUCCESS: '成功',
  WARNING: '警告',
  ERROR: '错误',
};

const TYPE_BADGE: Record<string, string> = {
  INFO: 'bg-sky-500/10 text-sky-600',
  SUCCESS: 'bg-emerald-500/10 text-emerald-600',
  WARNING: 'bg-amber-500/10 text-amber-700',
  ERROR: 'bg-destructive/10 text-destructive',
};

export default function NotificationsPage() {
  const { isLoading, isAuthenticated } = useAuth();
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const list = await api.getNotifications({ unread_only: unreadOnly, limit: 50 });
      setItems(Array.isArray(list) ? list : []);
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || '加载通知失败');
    } finally {
      setLoading(false);
    }
  }, [unreadOnly]);

  useEffect(() => {
    if (isAuthenticated) load();
  }, [isAuthenticated, load]);

  const markRead = async (id: string) => {
    setBusyId(id);
    try {
      await api.markNotificationRead(id);
      setItems((prev) =>
        unreadOnly ? prev.filter((n) => n.id !== id) : prev.map((n) => (n.id === id ? { ...n, read: true } : n))
      );
    } catch {
      setError('标记已读失败，请稍后重试');
    } finally {
      setBusyId(null);
    }
  };

  const remove = async (id: string) => {
    setBusyId(id);
    try {
      await api.deleteNotification(id);
      setItems((prev) => prev.filter((n) => n.id !== id));
    } catch {
      setError('删除通知失败，请稍后重试');
    } finally {
      setBusyId(null);
    }
  };

  const markAll = async () => {
    setBusyId('all');
    try {
      await api.markAllNotificationsRead();
      await load();
    } catch {
      setError('全部标记已读失败，请稍后重试');
    } finally {
      setBusyId(null);
    }
  };

  if (isLoading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <main className="page-container">
        <div className="section-card flex flex-col items-center justify-center px-6 py-20 text-center">
          <Bell className="h-8 w-8 text-muted-foreground" />
          <h1 className="mt-4 text-xl font-semibold text-foreground">请先登录</h1>
          <p className="mt-1.5 text-sm text-muted-foreground">登录后即可查看你的通知。</p>
          <Button asChild className="btn-primary mt-6">
            <a href="/">去登录</a>
          </Button>
        </div>
      </main>
    );
  }

  const unreadCount = items.filter((n) => !n.read).length;

  return (
    <main className="page-container">
      <section className="flex flex-col gap-4 pb-6 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">通知中心</h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            {unreadOnly ? `未读通知${items.length ? ` · ${items.length} 条` : ''}` : `共 ${items.length} 条，${unreadCount} 条未读`}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1 rounded-xl border border-border/70 bg-muted/50 p-1">
            <button
              type="button"
              onClick={() => setUnreadOnly(false)}
              className={cn(
                'rounded-lg px-3 py-1.5 text-sm font-medium transition-colors',
                !unreadOnly ? 'bg-card text-foreground shadow-soft' : 'text-muted-foreground'
              )}
            >
              全部
            </button>
            <button
              type="button"
              onClick={() => setUnreadOnly(true)}
              className={cn(
                'rounded-lg px-3 py-1.5 text-sm font-medium transition-colors',
                unreadOnly ? 'bg-card text-foreground shadow-soft' : 'text-muted-foreground'
              )}
            >
              未读
            </button>
          </div>
          <Button variant="outline" onClick={load} disabled={loading} className="rounded-xl">
            <RefreshCw className={cn('mr-2 h-4 w-4', loading && 'animate-spin')} />
            刷新
          </Button>
          <Button onClick={markAll} disabled={unreadCount === 0 || busyId === 'all'} className="btn-primary">
            {busyId === 'all' ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <CheckCheck className="mr-2 h-4 w-4" />
            )}
            全部已读
          </Button>
        </div>
      </section>

      {error && (
        <div role="alert" className="mb-4 rounded-xl border border-destructive/20 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {loading && items.length === 0 ? (
        <div className="flex items-center justify-center py-20 text-sm text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          加载中…
        </div>
      ) : items.length === 0 ? (
        <div className="section-card flex flex-col items-center justify-center px-6 py-20 text-center">
          <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-muted text-muted-foreground">
            <Bell className="h-6 w-6" />
          </div>
          <h2 className="text-lg font-semibold text-foreground">
            {unreadOnly ? '没有未读通知' : '还没有通知'}
          </h2>
          <p className="mt-1.5 max-w-sm text-sm text-muted-foreground">
            文档解析完成、工作流执行结束等事件会出现在这里。
          </p>
        </div>
      ) : (
        <ul className="section-card divide-y divide-border/70 overflow-hidden">
          {items.map((item) => (
            <li
              key={item.id}
              className={cn('flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-start', !item.read && 'bg-primary/[0.03]')}
            >
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className={cn(
                      'rounded-md px-2 py-0.5 text-[11px] font-semibold',
                      TYPE_BADGE[item.type] || 'bg-muted text-muted-foreground'
                    )}
                  >
                    {TYPE_LABEL[item.type] || item.type}
                  </span>
                  <h2
                    className={cn(
                      'text-sm',
                      item.read ? 'font-medium text-muted-foreground' : 'font-semibold text-foreground'
                    )}
                  >
                    {item.title}
                  </h2>
                  {!item.read && <span className="h-1.5 w-1.5 rounded-full bg-primary" aria-label="未读" />}
                </div>
                <p className="mt-1 whitespace-pre-line text-sm leading-relaxed text-muted-foreground">
                  {item.content}
                </p>
                <p className="mt-1.5 text-[11px] text-muted-foreground">
                  {formatRelativeTime(item.created_at)}
                </p>
              </div>

              <div className="flex flex-none items-center gap-1">
                {!item.read && (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => markRead(item.id)}
                    disabled={busyId === item.id}
                    className="rounded-lg text-xs"
                  >
                    {busyId === item.id ? (
                      <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <CheckCheck className="mr-1 h-3.5 w-3.5" />
                    )}
                    标记已读
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => remove(item.id)}
                  disabled={busyId === item.id}
                  aria-label={`删除通知 ${item.title}`}
                  className="rounded-lg text-xs text-muted-foreground hover:text-destructive"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
