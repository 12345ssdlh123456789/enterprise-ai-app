'use client';

import { useCallback, useEffect, useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { api } from '@/lib/api';
import { CostSummary, TokenBudget, UsageRecord } from '@/types';
import { formatCurrency, formatNumber } from '@/lib/utils';
import { DollarSign, Loader2, RefreshCw, Wallet } from 'lucide-react';

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription>{label}</CardDescription>
        <CardTitle className="text-2xl">{value}</CardTitle>
      </CardHeader>
      {hint && (
        <CardContent className="pt-0 text-xs text-muted-foreground">{hint}</CardContent>
      )}
    </Card>
  );
}

export default function CostsPage() {
  const [summary, setSummary] = useState<CostSummary | null>(null);
  const [budget, setBudget] = useState<TokenBudget | null>(null);
  const [records, setRecords] = useState<UsageRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [s, b, r] = await Promise.all([
        api.getCostSummary(),
        api.getBudget().catch(() => null),
        api.getUsageRecords({ limit: 50 }).catch(() => []),
      ]);
      setSummary(s);
      setBudget(b);
      setRecords(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载成本数据失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const usedPct = budget?.usage_percentage ?? 0;
  const byModel: Array<{ model?: string; cost?: number; tokens?: number; requests?: number }> =
    Array.isArray(summary?.by_model) ? summary!.by_model : [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">成本与用量</h1>
          <p className="text-sm text-muted-foreground">
            本月模型调用成本、token 预算与逐条用量记录。
          </p>
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

      {loading ? (
        <div className="flex items-center justify-center py-16 text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          加载中…
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat
              label="本月成本"
              value={formatCurrency(summary?.total_cost ?? 0)}
              hint={summary?.start_date ? `自 ${summary.start_date.slice(0, 10)} 起` : undefined}
            />
            <Stat
              label="本月 tokens"
              value={formatNumber(summary?.total_tokens ?? 0)}
              hint={`${formatNumber(summary?.total_requests ?? 0)} 次请求`}
            />
            <Stat
              label="预算上限"
              value={budget ? formatNumber(budget.limit) : '—'}
              hint={budget?.reset_at ? `${new Date(budget.reset_at).toLocaleDateString()} 重置` : undefined}
            />
            <Stat
              label="预算使用率"
              value={`${usedPct.toFixed(1)}%`}
              hint={budget ? `${formatNumber(budget.used)} / ${formatNumber(budget.limit)}` : undefined}
            />
          </div>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-lg">
                <Wallet className="h-5 w-5" />
                预算进度
              </CardTitle>
              <CardDescription>超过阈值后网关会拒绝新的模型调用。</CardDescription>
            </CardHeader>
            <CardContent>
              <div
                role="progressbar"
                aria-label="预算使用率"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round(Math.min(100, usedPct))}
                className="h-3 w-full overflow-hidden rounded-full bg-muted"
              >
                <div
                  className="h-full rounded-full bg-primary transition-all"
                  style={{ width: `${Math.min(100, usedPct)}%` }}
                />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-lg">
                <DollarSign className="h-5 w-5" />
                按模型统计
              </CardTitle>
              <CardDescription>成本、token 与请求数按模型拆分。</CardDescription>
            </CardHeader>
            <CardContent>
              {byModel.length === 0 ? (
                <p className="py-10 text-center text-sm text-muted-foreground">本月还没有模型调用</p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>模型</TableHead>
                      <TableHead className="text-right">请求数</TableHead>
                      <TableHead className="text-right">Tokens</TableHead>
                      <TableHead className="text-right">成本</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {byModel.map((row, i) => (
                      <TableRow key={row.model || i}>
                        <TableCell className="font-medium">{row.model || '—'}</TableCell>
                        <TableCell className="text-right">{formatNumber(row.requests ?? 0)}</TableCell>
                        <TableCell className="text-right">{formatNumber(row.tokens ?? 0)}</TableCell>
                        <TableCell className="text-right">{formatCurrency(row.cost ?? 0)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-lg">用量明细（最近 {records.length} 条）</CardTitle>
            </CardHeader>
            <CardContent>
              {records.length === 0 ? (
                <p className="py-10 text-center text-sm text-muted-foreground">
                  还没有用量记录；在对话页发起一次 AI 调用后会写入
                </p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>时间</TableHead>
                      <TableHead>模型</TableHead>
                      <TableHead className="text-right">输入</TableHead>
                      <TableHead className="text-right">输出</TableHead>
                      <TableHead className="text-right">成本</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {records.map((r) => (
                      <TableRow key={r.id}>
                        <TableCell className="text-sm text-muted-foreground">
                          {new Date(r.created_at).toLocaleString()}
                        </TableCell>
                        <TableCell>{r.model || '—'}</TableCell>
                        <TableCell className="text-right">{formatNumber(r.prompt_tokens ?? 0)}</TableCell>
                        <TableCell className="text-right">{formatNumber(r.completion_tokens ?? 0)}</TableCell>
                        <TableCell className="text-right">{formatCurrency(r.cost ?? 0)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
