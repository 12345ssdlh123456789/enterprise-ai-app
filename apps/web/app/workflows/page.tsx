'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/lib/auth';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Loader2, Plus, Search, Edit, Trash2, Copy, Play, FileText, Loader, GitBranch, Sparkles, CheckCircle2, AlertCircle, Clock, History } from 'lucide-react';
import { WorkflowRead } from '@/types';
import { formatRelativeTime, cn } from '@/lib/utils';
import { toast } from 'sonner';

const statusColors: Record<string, string> = {
  draft: 'bg-slate-100 text-slate-700 border-slate-200',
  published: 'bg-emerald-100 text-emerald-700 border-emerald-200',
  archived: 'bg-amber-100 text-amber-700 border-amber-200',
};

const statusLabels: Record<string, string> = {
  draft: '草稿',
  published: '已发布',
  archived: '已归档',
};

export default function WorkflowsPage() {
  const router = useRouter();
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const [workflows, setWorkflows] = useState<WorkflowRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [newWorkflowName, setNewWorkflowName] = useState('');
  const [newWorkflowDesc, setNewWorkflowDesc] = useState('');
  const [creating, setCreating] = useState(false);
  // 正在执行的工作流 id：只锁住被点的那张卡片，执行期间显示「执行中...」
  const [executingId, setExecutingId] = useState<string | null>(null);

  const loadWorkflows = async () => {
    try {
      const data = await api.getWorkflows({ limit: 100 });
      setWorkflows(data);
    } catch (error) {
      console.error('Failed to load workflows:', error);
      toast.error('加载工作流列表失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (authLoading) return;
    if (!isAuthenticated) {
      // 未登录时不发请求，但必须结束 loading：否则会一直卡在「加载中，请稍候...」
      setLoading(false);
      return;
    }
    loadWorkflows();
  }, [authLoading, isAuthenticated]);

  const handleCreate = async () => {
    if (!newWorkflowName.trim()) return;
    setCreating(true);
    try {
      const workflow = await api.createWorkflow({
        name: newWorkflowName,
        description: newWorkflowDesc,
        definition: { nodes: [], edges: [] },
      });
      setShowCreateDialog(false);
      setNewWorkflowName('');
      setNewWorkflowDesc('');
      toast.success('工作流创建成功');
      router.push(`/workflows/${workflow.id}/edit`);
    } catch (error) {
      console.error('Failed to create workflow:', error);
      toast.error('创建失败');
    } finally {
      setCreating(false);
    }
  };

  const handleDuplicate = async (workflow: WorkflowRead) => {
    try {
      const newWorkflow = await api.createWorkflow({
        name: `${workflow.name} (副本)`,
        description: workflow.description,
        definition: workflow.definition,
      });
      toast.success('工作流已复制');
      router.push(`/workflows/${newWorkflow.id}/edit`);
    } catch (error) {
      console.error('Failed to duplicate workflow:', error);
      toast.error('复制失败');
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('确定要删除这个工作流吗？此操作不可恢复。')) return;
    try {
      await api.deleteWorkflow(id);
      setWorkflows((prev) => prev.filter((w) => w.id !== id));
      toast.success('已删除');
    } catch (error) {
      console.error('Failed to delete workflow:', error);
      toast.error('删除失败');
    }
  };

  const handleExecute = async (workflow: WorkflowRead) => {
    setExecutingId(workflow.id);
    try {
      // 以前这里 router.push(`/workflows/{id}/execute`)，但那个页面根本不存在（点了就是 404）。
      // 现在直接在列表里真执行，然后跳到执行记录看节点明细。
      const result = await api.executeWorkflow(workflow.id, { input_data: {}, async_mode: false });
      if (result?.status === 'COMPLETED') {
        toast.success(`执行完成（${result.node_executions?.length ?? 0} 个节点）`);
      } else {
        toast.error(result?.error || '执行失败');
      }
      router.push(`/workflows/${workflow.id}/executions`);
    } catch (error: any) {
      console.error('Failed to execute workflow:', error);
      toast.error(error?.response?.data?.detail || '执行失败');
    } finally {
      setExecutingId(null);
    }
  };

  const filteredWorkflows = workflows.filter((w) =>
    (statusFilter === 'all' || w.status === statusFilter) &&
    (w.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      w.description?.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  const draftCount = workflows.filter(w => w.status === 'draft').length;
  const publishedCount = workflows.filter(w => w.status === 'published').length;
  const archivedCount = workflows.filter(w => w.status === 'archived').length;

  if (authLoading || loading) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <div className="glass p-8 rounded-3xl border border-border/50 flex flex-col items-center gap-4">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
          <p className="text-muted-foreground text-sm">加载中，请稍候...</p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <Card className="glass max-w-md p-8 text-center border border-border/50">
          <CardHeader>
            <AlertCircle className="mx-auto h-8 w-8 text-muted-foreground mb-4" />
            <CardTitle className="text-lg">请先登录</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">登录后即可管理工作流</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background relative">
      {/* Background decoration */}
      <div className="absolute top-0 right-0 w-72 h-72 bg-indigo-500/10 rounded-full blur-3xl -mr-32 -mt-16 pointer-events-none" />
      <div className="absolute bottom-0 left-0 w-72 h-72 bg-sky-500/10 rounded-full blur-3xl -ml-32 -mb-16 pointer-events-none" />

      {/* Header */}
      <header className="border-b bg-card/70 backdrop-blur sticky top-16 z-30 border-border/60">
        <div className="container mx-auto flex h-16 items-center justify-between px-4">
          <div className="flex items-center gap-4">
            <Button variant="ghost" size="icon" onClick={() => router.push('/')}>
              <ArrowLeftIcon />
            </Button>
            <div className="flex flex-col gap-1">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-xl bg-brand-gradient flex items-center justify-center">
                  <GitBranch className="h-4 w-4 text-white" />
                </div>
                <h1 className="text-xl font-bold text-foreground">工作流管理</h1>
              </div>
              <p className="text-sm text-muted-foreground">创建、编辑和执行自动化工作流</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Dialog open={showCreateDialog} onOpenChange={setShowCreateDialog}>
              <DialogTrigger asChild>
                <Button className="btn-primary">
                  <Plus className="mr-2 h-4 w-4" />
                  新建工作流
                </Button>
              </DialogTrigger>
              <DialogContent className="max-w-md p-0">
                <DialogHeader className="px-6 py-4">
                  <DialogTitle className="text-lg font-bold">创建工作流</DialogTitle>
                </DialogHeader>
                <div className="space-y-4 p-6">
                  <div className="space-y-2">
                    <Label htmlFor="wf-name" className="font-medium text-sm text-foreground">名称</Label>
                    <Input
                      id="wf-name"
                      value={newWorkflowName}
                      onChange={(e) => setNewWorkflowName(e.target.value)}
                      placeholder="例如：智能客服问答流程"
                      autoFocus
                      className="input-field"
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="wf-desc" className="font-medium text-sm text-foreground">描述 (可选)</Label>
                    <Input
                      id="wf-desc"
                      value={newWorkflowDesc}
                      onChange={(e) => setNewWorkflowDesc(e.target.value)}
                      placeholder="工作流用途说明"
                      className="input-field"
                    />
                  </div>
                </div>
                <DialogFooter className="p-4 border-t border-border/50">
                  <Button variant="outline" onClick={() => setShowCreateDialog(false)} className="w-full">
                    取消
                  </Button>
                  <Button onClick={handleCreate} disabled={creating || !newWorkflowName.trim()} className="w-full btn-primary">
                    {creating ? '创建中...' : '创建工作流'}
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </div>
        </div>

        {/* Search & Filter */}
        <div className="border-t px-4 py-3 bg-card/30 border-border/50 backdrop-blur">
          <div className="flex flex-wrap items-center gap-4">
            <div className="relative flex-1 max-w-md">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder="搜索工作流..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-10 input-field h-10"
              />
            </div>
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="input-field h-10 w-40">
                <SelectValue placeholder="全部状态" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部状态</SelectItem>
                <SelectItem value="draft">草稿</SelectItem>
                <SelectItem value="published">已发布</SelectItem>
                <SelectItem value="archived">已归档</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="container mx-auto p-4 md:p-6">
        {/* Stats */}
        <div className="grid gap-4 md:grid-cols-3 mb-6">
          <StatCard title="全部工作流" value={workflows.length} color="text-blue-600" icon={<GitBranch className="h-5 w-5" />} />
          <StatCard title="草稿" value={draftCount} color="text-gray-600" icon={<Clock className="h-5 w-5" />} />
          <StatCard title="已发布" value={publishedCount} color="text-green-600" icon={<CheckCircle2 className="h-5 w-5" />} />
        </div>

        {filteredWorkflows.length === 0 ? (
          <Card className="section-card flex flex-col items-center justify-center py-16 text-center">
            <FileText className="mx-auto h-14 w-14 text-muted-foreground mb-4" />
            <h3 className="text-lg font-medium text-foreground mb-2">暂无工作流</h3>
            <p className="text-sm text-muted-foreground mb-6 max-w-md">创建第一个工作流，开始编排自动化业务流程</p>
            <Button className="btn-primary">
              <Plus className="mr-2 h-4 w-4" />
              创建工作流
            </Button>
          </Card>
        ) : (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {filteredWorkflows.map((workflow) => (
              <WorkflowCard
                key={workflow.id}
                workflow={workflow}
                onEdit={() => router.push(`/workflows/${workflow.id}/edit`)}
                onDuplicate={() => handleDuplicate(workflow)}
                onDelete={() => handleDelete(workflow.id)}
                onExecute={() => handleExecute(workflow)}
                onViewExecutions={() => router.push(`/workflows/${workflow.id}/executions`)}
                executing={executingId === workflow.id}
              />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}

function ArrowLeftIcon() {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="19" y1="12" x2="5" y2="12" />
      <polyline points="12 19 5 12 12 5" />
    </svg>
  );
}

function StatCard({ title, value, color, icon }: { title: string; value: number; color: string; icon: React.ReactNode }) {
  return (
    <Card className="stat-card border-border/80">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-muted-foreground">{title}</p>
          <p className="text-2xl font-bold text-foreground">{value}</p>
        </div>
        <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center text-primary">
          {icon}
        </div>
      </div>
    </Card>
  );
}

function WorkflowCard({
  workflow,
  onEdit,
  onDuplicate,
  onDelete,
  onExecute,
  onViewExecutions,
  executing,
}: {
  workflow: WorkflowRead;
  onEdit: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
  onExecute: () => void;
  onViewExecutions: () => void;
  executing: boolean;
}) {
  const nodeCount = workflow.definition?.nodes?.length || 0;
  const edgeCount = workflow.definition?.edges?.length || 0;

  return (
    <Card className="feature-card group flex h-full flex-col">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between">
          <div className="flex-1 min-w-0">
            <CardTitle className="text-lg font-bold text-foreground truncate">{workflow.name}</CardTitle>
            <CardDescription className="text-sm text-muted-foreground">{workflow.description || '暂无描述'}</CardDescription>
          </div>
          <Badge variant="secondary" className={cn('ml-2 px-2.5 py-1 text-xs font-medium border', statusColors[String(workflow.status).toLowerCase()])}>
            {statusLabels[String(workflow.status).toLowerCase()] ?? workflow.status}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="flex-1 space-y-3">
        <div className="flex items-center gap-4 text-sm text-muted-foreground">
          <div className="flex items-center gap-1">
            <GitBranch className="h-3 w-3" />
            <span className="font-medium">v{workflow.version}</span>
          </div>
          <div className="flex items-center gap-1">
            <FileText className="h-3 w-3" />
            <span className="font-medium">{nodeCount} 节点</span>
          </div>
          <div className="flex items-center gap-1">
            <Clock className="h-3 w-3" />
            <span className="font-medium">{edgeCount} 连线</span>
          </div>
        </div>

        <div className="text-xs text-muted-foreground">
          <Clock className="h-3 w-3 mr-1" />
          更新于 {formatRelativeTime(workflow.updated_at)}
        </div>

        <div className="pt-2 border-t border-border/50 flex flex-wrap gap-2">
          {workflow.status === 'published' && (
            <Button
              variant="outline"
              size="sm"
              className="flex-1 min-w-[84px]"
              onClick={onExecute}
              disabled={nodeCount === 0 || executing}
            >
              {executing ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <Play className="mr-1 h-3 w-3" />}
              {executing ? '执行中...' : '执行'}
            </Button>
          )}
          <Button variant="outline" size="sm" className="flex-1 min-w-[84px]" onClick={onViewExecutions}>
            <History className="mr-1 h-3 w-3" />
            记录
          </Button>
          <Button variant="outline" size="sm" className="flex-1 min-w-[84px]" onClick={onEdit}>
            <Edit className="mr-1 h-3 w-3" />
            编辑
          </Button>
          <Button variant="ghost" size="sm" onClick={onDuplicate} className="h-8 w-8 p-0 group-hover:bg-muted/50">
            <Copy className="h-3 w-3" />
          </Button>
          <Button variant="ghost" size="sm" onClick={onDelete} className="h-8 w-8 p-0 group-hover:bg-red-50">
            <Trash2 className="h-3 w-3 text-destructive" />
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
