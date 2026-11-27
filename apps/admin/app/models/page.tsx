'use client';

import { useCallback, useEffect, useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { api } from '@/lib/api';
import { ModelConfig } from '@/types';
import { formatNumber } from '@/lib/utils';
import { Brain, Loader2, RefreshCw } from 'lucide-react';

const CAPABILITY_LABELS: Record<string, string> = {
  CHAT: '对话',
  EMBEDDING: '向量',
  RERANK: '重排',
  VISION: '视觉',
  FUNCTION_CALLING: '函数调用',
};

export default function ModelsPage() {
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [savingId, setSavingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setModels(await api.getModels({ limit: 200 }));
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载模型失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const toggle = async (model: ModelConfig) => {
    setSavingId(model.id);
    try {
      const updated = await api.updateModel(model.id, { enabled: !model.enabled });
      setModels((list) => list.map((m) => (m.id === updated.id ? updated : m)));
    } catch (e) {
      setError(e instanceof Error ? e.message : '更新模型失败');
    } finally {
      setSavingId(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold">模型配置</h1>
          <p className="text-sm text-muted-foreground">
            统一管理可用的大模型；停用后网关不再向该模型路由请求。
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

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-lg">
            <Brain className="h-5 w-5" />
            已注册模型（{models.length}）
          </CardTitle>
          <CardDescription>价格来自模型配置，按每 1K tokens 计。</CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex items-center justify-center py-12 text-muted-foreground">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              加载中…
            </div>
          ) : models.length === 0 ? (
            <p className="py-12 text-center text-sm text-muted-foreground">还没有注册模型</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>模型</TableHead>
                  <TableHead>提供商</TableHead>
                  <TableHead>能力</TableHead>
                  <TableHead className="text-right">上下文</TableHead>
                  <TableHead className="text-right">输入 / 输出</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {models.map((m) => {
                  const input = m.pricing?.input_per_1m ?? m.pricing?.input ?? null;
                  const output = m.pricing?.output_per_1m ?? m.pricing?.output ?? null;
                  return (
                    <TableRow key={m.id}>
                      <TableCell className="font-medium">{m.name}</TableCell>
                      <TableCell>
                        <Badge variant="secondary">{m.provider}</Badge>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1">
                          {m.capabilities.map((c) => (
                            <Badge key={c} variant="outline">
                              {CAPABILITY_LABELS[c] || c}
                            </Badge>
                          ))}
                        </div>
                      </TableCell>
                      <TableCell className="text-right">{formatNumber(m.context_window)}</TableCell>
                      <TableCell className="text-right text-sm text-muted-foreground">
                        {input ?? '—'} / {output ?? '—'}
                      </TableCell>
                      <TableCell>
                        <Badge variant={m.enabled ? 'default' : 'secondary'}>
                          {m.enabled ? '已启用' : '已停用'}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => toggle(m)}
                          disabled={savingId === m.id}
                        >
                          {savingId === m.id && <Loader2 className="mr-2 h-3 w-3 animate-spin" />}
                          {m.enabled ? '停用' : '启用'}
                        </Button>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
