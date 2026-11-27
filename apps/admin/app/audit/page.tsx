'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { api } from '@/lib/api';
import { AuditLog } from '@/types';
import { formatRelativeTime } from '@/lib/utils';
import { Loader2, RefreshCw, ScrollText, Search } from 'lucide-react';

const STATUS_STYLE: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  success: 'default',
  failed: 'destructive',
};

export default function AuditPage() {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('all');
  const [selected, setSelected] = useState<AuditLog | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setLogs(await api.getAuditLogs({ limit: 200 }));
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载审计日志失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const filtered = useMemo(
    () =>
      logs.filter((l) => {
        const matchesQuery =
          !query ||
          l.action.toLowerCase().includes(query.toLowerCase()) ||
          l.resource.toLowerCase().includes(query.toLowerCase()) ||
          (l.ip_address || '').includes(query);
        const state = l.success ? 'success' : 'failed';
        const matchesStatus = status === 'all' || state === status;
        return matchesQuery && matchesStatus;
      }),
    [logs, query, status]
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">审计日志</h1>
          <p className="text-sm text-muted-foreground">只读、追加写入，覆盖登录、配置变更等敏感操作。</p>
        </div>
        <Button variant="outline" onClick={load} disabled={loading}>
          <RefreshCw className="mr-2 h-4 w-4" />
          刷新
        </Button>
      </div>

      {error && (
        <div role="alert" className="rounded-md border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-lg">
            <ScrollText className="h-5 w-5" />
            事件（{filtered.length}）
          </CardTitle>
          <CardDescription>按操作、资源或 IP 过滤。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative max-w-sm flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                aria-label="搜索审计事件"
                className="pl-9"
                placeholder="搜索 action / 资源 / IP…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
            <select
              aria-label="按状态过滤"
              className="h-10 rounded-md border border-input bg-background px-3 text-sm"
              value={status}
              onChange={(e) => setStatus(e.target.value)}
            >
              <option value="all">全部状态</option>
              <option value="success">成功</option>
              <option value="failed">失败</option>
            </select>
          </div>

          {loading ? (
            <div className="flex items-center justify-center py-12 text-muted-foreground">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              加载中…
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>时间</TableHead>
                  <TableHead>操作</TableHead>
                  <TableHead>资源</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>IP</TableHead>
                  <TableHead className="text-right">明细</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filtered.map((l) => (
                  <TableRow key={l.id}>
                    <TableCell className="whitespace-nowrap text-sm text-muted-foreground">
                      {formatRelativeTime(l.created_at)}
                    </TableCell>
                    <TableCell className="font-mono text-sm">{l.action}</TableCell>
                    <TableCell className="text-sm">
                      {l.resource}
                      {l.resource_id ? <span className="text-muted-foreground"> / {l.resource_id.slice(0, 8)}</span> : null}
                    </TableCell>
                    <TableCell>
                      <Badge variant={STATUS_STYLE[l.success ? 'success' : 'failed'] || 'outline'}>
                        {l.success ? '成功' : '失败'}
                      </Badge>
                    </TableCell>
                    <TableCell className="font-mono text-xs text-muted-foreground">
                      {l.ip_address || '—'}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={`查看 ${l.action} 的事件明细`}
                        onClick={() => setSelected(l)}
                      >
                        查看
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
                {filtered.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={6} className="py-12 text-center text-sm text-muted-foreground">
                      没有匹配的审计事件
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Dialog open={!!selected} onOpenChange={(open) => !open && setSelected(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>审计事件明细</DialogTitle>
            <DialogDescription>{selected?.action}</DialogDescription>
          </DialogHeader>
          {selected && (
            <div className="space-y-3 text-sm">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <p className="text-muted-foreground">资源</p>
                  <p className="font-mono">{selected.resource}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">资源 ID</p>
                  <p className="font-mono break-all">{selected.resource_id || '—'}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">状态</p>
                  <p>{selected.success ? '成功' : '失败'}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">时间</p>
                  <p>{new Date(selected.created_at).toLocaleString()}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">用户 ID</p>
                  <p className="font-mono break-all">{selected.user_id || '—'}</p>
                </div>
                <div>
                  <p className="text-muted-foreground">User Agent</p>
                  <p className="truncate" title={selected.user_agent || ''}>{selected.user_agent || '—'}</p>
                </div>
              </div>
              {selected.error_message && (
                <div>
                  <p className="mb-1 text-muted-foreground">错误信息</p>
                  <p className="text-destructive">{selected.error_message}</p>
                </div>
              )}
              <div>
                <p className="mb-1 text-muted-foreground">变更</p>
                <pre className="max-h-64 overflow-auto rounded-md bg-muted p-3 text-xs">
                  {JSON.stringify(
                    { old_value: selected.old_value ?? null, new_value: selected.new_value ?? null },
                    null,
                    2
                  )}
                </pre>
              </div>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setSelected(null)}>
              关闭
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
