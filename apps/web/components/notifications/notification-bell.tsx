'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { Bell, CheckCheck, Loader2 } from 'lucide-react';

import { api } from '@/lib/api';
import { cn, formatRelativeTime } from '@/lib/utils';
import { NotificationItem } from '@/types';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

const TYPE_DOT: Record<string, string> = {
  INFO: 'bg-sky-500',
  SUCCESS: 'bg-emerald-500',
  WARNING: 'bg-amber-500',
  ERROR: 'bg-destructive',
};

/**
 * 导航栏通知铃铛：未读数 + 最近 6 条 + 「全部已读」。
 *
 * 数据来自网关 `/api/v1/notifications`（默认单体，或 `GATEWAY_PROXY_NOTIFICATIONS=true`
 * 时由 notification-service 提供，前端不感知）。加载失败静默降级，不打断导航栏。
 */
export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<NotificationItem[]>([]);
  const [unread, setUnread] = useState(0);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [list, count] = await Promise.all([
        api.getNotifications({ limit: 6 }),
        api.getUnreadNotificationCount(),
      ]);
      setItems(Array.isArray(list) ? list : []);
      setUnread(count);
    } catch {
      // 未登录 / 网关没起：保持空列表，不弹错误
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  const markAll = async () => {
    try {
      await api.markAllNotificationsRead();
    } finally {
      await load();
    }
  };

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={unread > 0 ? `通知（${unread} 条未读）` : '通知'}
          className="relative flex h-10 w-10 items-center justify-center rounded-xl text-muted-foreground transition-colors hover:bg-muted hover:text-primary"
        >
          <Bell className="h-5 w-5" />
          {unread > 0 && (
            <span className="absolute right-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[10px] font-semibold leading-none text-white">
              {unread > 99 ? '99+' : unread}
            </span>
          )}
        </button>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="end" className="w-80 p-0">
        <div className="flex items-center justify-between border-b border-border/70 px-4 py-3">
          <div>
            <p className="text-sm font-semibold text-foreground">通知</p>
            <p className="text-[11px] text-muted-foreground">
              {unread > 0 ? `${unread} 条未读` : '全部已读'}
            </p>
          </div>
          <button
            type="button"
            onClick={markAll}
            disabled={unread === 0}
            className="flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-primary transition-colors hover:bg-primary/10 disabled:text-muted-foreground disabled:opacity-60"
          >
            <CheckCheck className="h-3.5 w-3.5" />
            全部已读
          </button>
        </div>

        <div className="max-h-80 overflow-y-auto">
          {loading && items.length === 0 ? (
            <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              加载中…
            </div>
          ) : items.length === 0 ? (
            <p className="px-4 py-10 text-center text-sm text-muted-foreground">还没有通知</p>
          ) : (
            <ul className="divide-y divide-border/60">
              {items.map((item) => (
                <li key={item.id}>
                  <Link
                    href="/notifications"
                    onClick={() => setOpen(false)}
                    className="flex gap-3 px-4 py-3 transition-colors hover:bg-muted/60"
                  >
                    <span
                      className={cn(
                        'mt-1.5 h-2 w-2 flex-none rounded-full',
                        TYPE_DOT[item.type] || 'bg-muted-foreground',
                        item.read && 'opacity-30'
                      )}
                      aria-hidden="true"
                    />
                    <span className="min-w-0">
                      <span
                        className={cn(
                          'block truncate text-sm',
                          item.read ? 'text-muted-foreground' : 'font-medium text-foreground'
                        )}
                      >
                        {item.title}
                      </span>
                      <span className="mt-0.5 line-clamp-2 block text-xs leading-relaxed text-muted-foreground">
                        {item.content}
                      </span>
                      <span className="mt-1 block text-[11px] text-muted-foreground">
                        {formatRelativeTime(item.created_at)}
                      </span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="border-t border-border/70 p-2">
          <Link
            href="/notifications"
            onClick={() => setOpen(false)}
            className="block rounded-lg px-3 py-2 text-center text-sm font-medium text-primary transition-colors hover:bg-primary/10"
          >
            查看全部通知
          </Link>
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
