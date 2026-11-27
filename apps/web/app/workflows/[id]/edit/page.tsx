'use client';

import { useState, useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useAuth } from '@/lib/auth';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { Loader2, ChevronLeft, Play, AlertTriangle, GitBranch, FileText, History } from 'lucide-react';
import { WorkflowRead, WorkflowDefinition } from '@/types';
import { formatRelativeTime, cn } from '@/lib/utils';
import { toast } from 'sonner';
import { WorkflowEditor } from '@/components/workflow/workflow-editor';

export default function WorkflowEditPage() {
  const params = useParams();
  const router = useRouter();
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const workflowId = params.id as string;

  const [workflow, setWorkflow] = useState<WorkflowRead | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [executing, setExecuting] = useState(false);

  const loadWorkflow = async () => {
    try {
      const data = await api.getWorkflow(workflowId);
      setWorkflow(data);
    } catch (error) {
      console.error('Failed to load workflow:', error);
      toast.error('加载工作流失败');
      router.push('/workflows');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isAuthenticated) {
      loadWorkflow();
    }
  }, [isAuthenticated, workflowId]);

  const handleSave = async (definition: WorkflowDefinition) => {
    if (!workflow) return;
    setSaving(true);
    try {
      await api.updateWorkflow(workflowId, { definition });
      setWorkflow(prev => prev ? { ...prev, definition, updated_at: new Date().toISOString() } : null);
      toast.success('保存成功');
    } catch (error) {
      console.error('Failed to save workflow:', error);
      toast.error('保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleExecute = async () => {
    if (!workflow) return;
    setExecuting(true);
    try {
      const result = await api.executeWorkflow(workflowId, { input_data: {}, async_mode: false });
      // 默认执行器会真实返回 COMPLETED / FAILED（不再是一律“提交成功”），失败要把原因说出来
      if (result?.status === 'COMPLETED') {
        toast.success(`执行完成（${result.node_executions?.length ?? 0} 个节点）`);
      } else {
        toast.error(result?.error || '执行失败');
      }
      console.log('Execution result:', result);
    } catch (error) {
      console.error('Failed to execute workflow:', error);
      toast.error('执行失败');
    } finally {
      setExecuting(false);
    }
  };

  const handleValidate = async (definition: WorkflowDefinition) => {
    try {
      const result = await api.validateWorkflowDefinition(definition);
      if (result.valid) {
        toast.success('验证通过');
      } else {
        toast.error(`发现 ${result.errors.length} 个错误`);
      }
    } catch (error) {
      toast.error('验证失败');
    }
  };

  if (authLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <Card className="glass max-w-md border border-border/50 p-8 text-center">
          <CardHeader>
            <CardTitle className="text-lg">请先登录</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <p className="text-sm text-muted-foreground">登录后即可编辑工作流</p>
            <Button onClick={() => router.push('/')}>
              <ChevronLeft className="mr-2 h-4 w-4" />
              返回登录
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (!workflow) {
    return <div className="flex h-screen items-center justify-center">工作流不存在</div>;
  }

  const statusColors: Record<string, string> = {
    draft: 'bg-gray-100 text-gray-800',
    published: 'bg-green-100 text-green-800',
    archived: 'bg-yellow-100 text-yellow-800',
  };

  const statusLabels: Record<string, string> = {
    draft: '草稿',
    published: '已发布',
    archived: '已归档',
  };

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b bg-card/80 backdrop-blur sticky top-16 z-30">
        <div className="container mx-auto flex h-16 items-center justify-between px-4">
          <div className="flex items-center gap-4">
            <Button variant="ghost" size="icon" onClick={() => router.push('/workflows')}>
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <div className="min-w-0">
              <h1 className="text-xl font-bold truncate max-w-[300px]">{workflow.name}</h1>
              <p className="text-sm text-muted-foreground">
                v{workflow.version} • {workflow.definition?.nodes?.length || 0} 节点
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Badge variant="secondary" className={cn(statusColors[String(workflow.status).toLowerCase()], 'mr-2')}>
              {statusLabels[String(workflow.status).toLowerCase()] ?? workflow.status}
            </Badge>

            {/* 验证/保存统一由编辑器工具栏触发，避免这里保存的是接口返回的旧定义 */}

            <Button variant="outline" onClick={() => router.push(`/workflows/${workflowId}/executions`)}>
              <History className="mr-2 h-4 w-4" />
              执行记录
            </Button>

            {workflow.status === 'published' && (
              <Button onClick={handleExecute} disabled={executing}>
                <Play className="mr-2 h-4 w-4" />
                {executing ? '执行中...' : '执行'}
              </Button>
            )}
          </div>
        </div>
      </header>

      {/* Editor */}
      <main className="flex-1">
        <WorkflowEditor
          initialNodes={workflow.definition?.nodes || []}
          initialEdges={workflow.definition?.edges || []}
          initialName={workflow.name}
          initialDescription={workflow.description || ''}
          onSave={handleSave}
          onValidate={handleValidate}
          onExecute={handleExecute}
          availableModels={['gpt-4o-mini', 'gpt-4o', 'claude-3-5-sonnet', 'claude-3-haiku']}
          availableKnowledgeBases={[]}
        />
      </main>
    </div>
  );
}
