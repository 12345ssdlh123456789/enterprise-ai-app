'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useAuth } from '@/lib/auth';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { api } from '@/lib/api';
import { AuditLog, CostSummary, ModelConfig, Tenant, User } from '@/types';
import { formatCurrency, formatNumber, formatRelativeTime } from '@/lib/utils';
import { Loader2, Users, Building2, Brain, DollarSign, ScrollText, ArrowUpRight, RefreshCw } from 'lucide-react';

interface Overview {
  users: User[];
  tenants: Tenant[];
  models: ModelConfig[];
  cost: CostSummary | null;
  audit: AuditLog[];
}

export default function AdminPage() {
  const { user } = useAuth();
  const [data, setData] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const [users, tenants, models, cost, audit] = await Promise.all([
        api.getUsers({ limit: 100 }),
        api.getTenants({ limit: 100 }),
        api.getModels({ limit: 100 }),
        api.getCostSummary().catch(() => null),
        api.getAuditLogs({ limit: 8 }).catch(() => []),
      ]);
      setData({ users, tenants, models, cost, audit });
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载总览失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const stats = [
    {
      label: '用户',
      value: data?.users.length ?? 0,
      sub: `${data?.users.filter((u) => u.is_active).length ?? 0} 个启用`,
      icon: Users,
      href: '/users',
    },
    {
      label: '租户',
      value: data?.tenants.length ?? 0,
      sub: '数据隔离边界',
      icon: Building2,
      href: '/tenants',
    },
    {
      label: '模型',
      value: data?.models.length ?? 0,
      sub: `${data?.models.filter((m) => m.enabled).length ?? 0} 个已启用`,
      icon: Brain,
      href: '/models',
    },
    {
      label: '本月成本',
      value: formatCurrency(data?.cost?.total_cost ?? 0),
      sub: `${formatNumber(data?.cost?.total_tokens ?? 0)} tokens`,
      icon: DollarSign,
      href: '/costs',
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">总览</h1>
          <p className="text-sm text-muted-foreground">
            欢迎回来{user?.full_name ? `，${user.full_name}` : ''}。这里是当前租户的运行概览。
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

      {loading && !data ? (
        <div className="flex items-center justify-center py-16 text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          加载中…
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {stats.map((s) => (
              <Link key={s.label} href={s.href}>
                <Card className="transition-shadow hover:shadow-md">
                  <CardHeader className="pb-2">
                    <div className="flex items-center justify-between">
                      <CardDescription>{s.label}</CardDescription>
                      <s.icon className="h-4 w-4 text-muted-foreground" />
                    </div>
                    <CardTitle className="text-2xl">{s.value}</CardTitle>
                  </CardHeader>
                  <CardContent className="pt-0 text-xs text-muted-foreground">{s.sub}</CardContent>
                </Card>
              </Link>
            ))}
          </div>

          <Card>
            <CardHeader className="flex-row items-center justify-between space-y-0">
              <div>
                <CardTitle className="flex items-center gap-2 text-lg">
                  <ScrollText className="h-5 w-5" />
                  最近审计事件
                </CardTitle>
                <CardDescription>最新 8 条敏感操作记录。</CardDescription>
              </div>
              <Button asChild variant="ghost" size="sm">
                <Link href="/audit">
                  全部
                  <ArrowUpRight className="ml-1 h-4 w-4" />
                </Link>
              </Button>
            </CardHeader>
            <CardContent>
              {!data?.audit.length ? (
                <p className="py-10 text-center text-sm text-muted-foreground">
                  还没有审计事件；登录、改配置后会写入
                </p>
              ) : (
                <ul className="divide-y">
                  {data.audit.map((log) => (
                    <li key={log.id} className="flex items-center justify-between py-3 text-sm">
                      <div className="flex items-center gap-3">
                        <Badge variant={log.success ? 'default' : 'destructive'}>
                          {log.success ? '成功' : '失败'}
                        </Badge>
                        <span className="font-mono">{log.action}</span>
                        <span className="text-muted-foreground">{log.resource}</span>
                      </div>
                      <span className="text-muted-foreground">{formatRelativeTime(log.created_at)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
