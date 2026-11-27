'use client';

import { useEffect, useMemo, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useAuth } from '@/lib/auth';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import {
  Loader2,
  ChevronLeft,
  ChevronDown,
  ChevronRight,
  RefreshCw,
  AlertCircle,
  FileText,
} from 'lucide-react';
import type { WorkflowExecution, WorkflowRead } from '@/types';
import { cn, formatDateTime, formatRelativeTime } from '@/lib/utils';
import {
  executionDurationMs,
  executionStatusMeta,
  formatDuration,
  nodeLabel,
  nodeNameMap,
  nodeOutputPreview,
} from '@/lib/workflow-executions';
import { toast } from 'sonner';

export default function WorkflowExecutionsPage() {
  const params = useParams();
  const router = useRouter();
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const workflowId = params.id as string;

  const [workflow, setWorkflow] = useState<WorkflowRead | null>(null);
  const [executions, setExecutions] = useState<WorkflowExecution[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const nodeNames = useMemo(() => nodeNameMap(workflow?.definition), [workflow?.definition]);

  const fetchExecutions = async (filter: string) =>
    api.getWorkflowExecutions(workflowId, {
      limit: 50,
      ...(filter === 'all' ? {} : { status: filter }),
    });

  useEffect(() => {
    if (authLoading) return;
    if (!isAuthenticated) {
      setLoading(false);
      return;
    }

    let cancelled = false;
    (async () => {
      setLoading(true);
      setError('');
      try {
        const [wf, list] = await Promise.all([
          // 工作流详情只用来补节点名；拿不到不影响看执行记录
          api.getWorkflow(workflowId).catch(() => null),
          fetchExecutions(statusFilter),
        ]);
        if (cancelled) return;
        if (wf) setWorkflow(wf);
        setExecutions(Array.isArray(list) ? list : []);
      } catch (err) {
        console.error('Failed to load workflow executions:', err);
        if (!cancelled) setError('加载执行记录失败，请稍后重试');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authLoading, isAuthenticated, workflowId, statusFilter]);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      const list = await fetchExecutions(statusFilter);
      setExecutions(Array.isArray(list) ? list : []);
      toast.success('已刷新');
    } catch (err) {
      console.error('Failed to refresh executions:', err);
      toast.error('刷新失败');
    } finally {
      setRefreshing(false);
    }
  };

  const toggle = (id: string) => setExpanded((prev) => ({ ...prev, [id]: !prev[id] }));

  if (authLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <Card className="glass max-w-md p-8 text-center border border-border/50">
          <p className="text-lg font-semibold">请先登录</p>
          <p className="mt-2 text-sm text-muted-foreground">登录后即可查看工作流执行记录</p>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b bg-card/70 backdrop-blur sticky top-16 z-30 border-border/60">
        <div className="container mx-auto flex flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="icon" onClick={() => router.push('/workflows')}>
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <div className="min-w-0">
              <h1 className="text-xl font-bold text-foreground">执行记录</h1>
              <p className="truncate text-sm text-muted-foreground">
                {workflow ? workflow.name : workflowId} · 最近 50 次
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="input-field h-9 w-32">
                <SelectValue placeholder="全部状态" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部状态</SelectItem>
                <SelectItem value="COMPLETED">成功</SelectItem>
                <SelectItem value="FAILED">失败</SelectItem>
                <SelectItem value="RUNNING">执行中</SelectItem>
              </SelectContent>
            </Select>
            <Button variant="outline" size="sm" onClick={handleRefresh} disabled={refreshing || loading}>
              <RefreshCw className={cn('mr-2 h-3.5 w-3.5', refreshing && 'animate-spin')} />
              刷新
            </Button>
            <Button variant="outline" size="sm" onClick={() => router.push(`/workflows/${workflowId}/edit`)}>
              <FileText className="mr-2 h-3.5 w-3.5" />
              编辑器
            </Button>
          </div>
        </div>
      </header>

      <main className="container mx-auto space-y-3 p-4 md:p-6">
        {loading ? (
          <div className="flex justify-center py-16">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
          </div>
        ) : error ? (
          <Card className="p-8 text-center">
            <AlertCircle className="mx-auto mb-3 h-8 w-8 text-destructive" />
            <p className="text-sm text-muted-foreground">{error}</p>
          </Card>
        ) : executions.length === 0 ? (
          <Card className="flex flex-col items-center justify-center py-16 text-center">
            <FileText className="mx-auto mb-4 h-14 w-14 text-muted-foreground" />
            <h3 className="mb-2 text-lg font-medium text-foreground">暂无执行记录</h3>
            <p className="max-w-md text-sm text-muted-foreground">
              在工作流列表或编辑器里点「执行」，跑完就会出现在这里（节点明细、耗时、错误都会记录）。
            </p>
          </Card>
        ) : (
          executions.map((execution) => {
            const meta = executionStatusMeta(execution.status);
            const nodes = execution.node_executions ?? [];
            const doneCount = nodes.filter((node) => node.status === 'completed').length;
            const isOpen = Boolean(expanded[execution.id]);

            return (
              <Card key={execution.id} className="overflow-hidden border-border/60">
                <button
                  type="button"
                  onClick={() => toggle(execution.id)}
                  className="flex w-full items-center gap-3 p-4 text-left transition-colors hover:bg-muted/40"
                  aria-expanded={isOpen}
                >
                  <Badge variant="secondary" className={cn('px-2.5 py-1 text-xs font-medium border', meta.className)}>
                    {meta.label}
                  </Badge>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-foreground">
                      {execution.started_at ? formatDateTime(execution.started_at) : '—'}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {execution.started_at ? formatRelativeTime(execution.started_at) : '时间未知'} ·{' '}
                      {doneCount}/{nodes.length} 节点完成 · 耗时 {formatDuration(executionDurationMs(execution))}
                    </p>
                  </div>
                  {execution.error && <AlertCircle className="h-4 w-4 shrink-0 text-destructive" />}
                  {isOpen ? (
                    <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
                  ) : (
                    <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                  )}
                </button>

                {isOpen && (
                  <div className="space-y-3 border-t border-border/60 px-4 py-3">
                    {execution.error && (
                      <div className="rounded-xl bg-destructive/10 p-3 text-sm text-destructive">
                        {execution.error}
                      </div>
                    )}

                    {nodes.length === 0 ? (
                      <p className="text-sm text-muted-foreground">
                        这次执行没有节点明细（旧记录，或执行在进入节点前就失败了）。
                      </p>
                    ) : (
                      <ul className="space-y-2">
                        {nodes.map((node, index) => {
                          const nodeMeta = executionStatusMeta(node.status);
                          const preview = nodeOutputPreview(node.output);
                          return (
                            <li key={`${node.node_id}-${index}`} className="rounded-xl border border-border/60 p-3">
                              <div className="flex flex-wrap items-center gap-2">
                                <span className="text-xs text-muted-foreground">#{index + 1}</span>
                                <span className="text-sm font-medium text-foreground">
                                  {nodeLabel(node, nodeNames)}
                                </span>
                                <span className="text-xs text-muted-foreground">({node.node_id})</span>
                                <Badge
                                  variant="secondary"
                                  className={cn('ml-auto px-2 py-0.5 text-[11px] border', nodeMeta.className)}
                                >
                                  {nodeMeta.label}
                                </Badge>
                                <span className="text-xs text-muted-foreground">
                                  {formatDuration(node.duration_ms)}
                                </span>
                              </div>

                              {node.error && <p className="mt-1 text-xs text-destructive">{node.error}</p>}
                              {preview && (
                                <p className="mt-1 break-all font-mono text-xs text-muted-foreground">{preview}</p>
                              )}
                              {node.output != null && (
                                <details className="mt-1">
                                  <summary className="cursor-pointer text-xs text-primary">完整输出</summary>
                                  <pre className="mt-1 max-h-64 overflow-auto rounded-lg bg-muted/60 p-2 text-[11px] leading-relaxed">
                                    {JSON.stringify(node.output, null, 2)}
                                  </pre>
                                </details>
                              )}
                            </li>
                          );
                        })}
                      </ul>
                    )}

                    {execution.output != null && (
                      <details>
                        <summary className="cursor-pointer text-sm font-medium text-foreground">最终输出</summary>
                        <pre className="mt-2 max-h-80 overflow-auto rounded-xl bg-muted/60 p-3 text-xs leading-relaxed">
                          {JSON.stringify(execution.output, null, 2)}
                        </pre>
                      </details>
                    )}
                  </div>
                )}
              </Card>
            );
          })
        )}
      </main>
    </div>
  );
}
