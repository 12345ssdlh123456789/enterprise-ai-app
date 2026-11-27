'use client';

import { useAuth } from '@/lib/auth';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter, DialogDescription } from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { useState, useEffect } from 'react';
import { api } from '@/lib/api';
import { KnowledgeBase } from '@/types';
import { formatRelativeTime, cn } from '@/lib/utils';
import { Plus, Search, Settings, Upload, Trash2, Edit, FileText, Loader2, MessageSquare, Users, ShieldCheck, Zap, Activity } from 'lucide-react';

export default function KnowledgeBasesPage() {
  const { user, tenant, isLoading, isAuthenticated } = useAuth();
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [showCreateKb, setShowCreateKb] = useState(false);
  const [newKbName, setNewKbName] = useState('');
  const [newKbDesc, setNewKbDesc] = useState('');
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    if (isLoading) return;
    if (!isAuthenticated) {
      // 未登录时不能发请求，但要把 loading 结束掉，避免永远显示加载中
      setLoading(false);
      return;
    }
    fetchKbs();
  }, [isLoading, isAuthenticated]);

  const fetchKbs = async () => {
    try {
      const data = await api.getKnowledgeBases({ limit: 50 });
      setKbs(data);
    } catch (error) {
      console.error('Failed to fetch KBs:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateKb = async () => {
    if (!newKbName.trim()) return;
    setCreating(true);
    try {
      await api.createKnowledgeBase({
        name: newKbName,
        description: newKbDesc,
      });
      setShowCreateKb(false);
      setNewKbName('');
      setNewKbDesc('');
      fetchKbs();
    } catch (error: any) {
      console.error('Failed to create KB:', error);
    } finally {
      setCreating(false);
    }
  };

  const filteredKbs = kbs.filter(kb =>
    kb.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    kb.description?.toLowerCase().includes(searchQuery.toLowerCase())
  );

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
          <p className="text-muted-foreground text-sm">正在加载...</p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-brand-blue-50 via-brand-indigo-50 to-brand-purple-50 px-4">
        <div className="max-w-md w-full">
          <Card className="glass-panel border border-border/50 shadow-xl">
            <CardHeader className="text-center space-y-2">
              <div className="inline-flex items-center justify-center gap-2 w-12 h-12 rounded-2xl bg-brand-gradient text-white mx-auto mb-4 flex-shrink-0">
                <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 2L2 7l10 5 10-5-10-5z" />
                  <path d="M2 17l10 5 10-5" />
                  <path d="M2 12l10 5 10-5" />
                </svg>
              </div>
              <CardTitle className="text-2xl font-bold tracking-tight">欢迎使用智汇 AI 工作台</CardTitle>
              <CardDescription className="text-muted-foreground">
                企业级智能客服 / 知识库助手平台
              </CardDescription>
            </CardHeader>
          </Card>
        </div>
      </div>
    );
  }

  return (
    <div className="page-container space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">知识库管理</h1>
          <p className="text-muted-foreground">管理您的知识库，上传文档并构建 AI 知识助手</p>
        </div>
        <Button className="btn-primary" onClick={() => setShowCreateKb(true)}>
          <Plus className="mr-2 h-4 w-4" />
          新建知识库
        </Button>
      </div>

      <div className="flex items-center gap-4 max-w-lg">
        <Label htmlFor="search" className="sr-only">搜索</Label>
        <Input
          id="search"
          placeholder="搜索知识库..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="input-field"
        />
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {filteredKbs.length === 0 ? (
          <div className="col-span-full">
            <Card className="glass border border-border/50">
              <CardContent className="py-20 text-center">
                <div className="w-16 h-16 rounded-full bg-secondary/50 flex items-center justify-center mx-auto mb-6 text-muted-foreground">
                  <FileText className="h-8 w-8" />
                </div>
                <h3 className="text-xl font-bold text-foreground mb-2">暂无知识库</h3>
                <p className="text-muted-foreground mb-6">创建第一个知识库开始使用</p>
                <Button className="btn-primary" onClick={() => setShowCreateKb(true)}>
                  <Plus className="mr-2 h-4 w-4" />
                  新建知识库
                </Button>
              </CardContent>
            </Card>
          </div>
        ) : (
          filteredKbs.map((kb) => (
            <KnowledgeBaseCard key={kb.id} kb={kb} onRefresh={fetchKbs} />
          ))
        )}
      </div>

      <Dialog open={showCreateKb} onOpenChange={setShowCreateKb}>
        <DialogTrigger asChild>
          <Button className="hidden">Create KB</Button>
        </DialogTrigger>
        <DialogContent className="sm:max-w-[420px]">
          <DialogHeader>
            <DialogTitle>新建知识库</DialogTitle>
            <DialogDescription>输入知识库名称和描述</DialogDescription>
          </DialogHeader>
          <form className="space-y-4">
            <Label htmlFor="kb-name">知识库名称</Label>
            <Input
              id="kb-name"
              placeholder="例如：产品文档知识库"
              value={newKbName}
              onChange={(e) => setNewKbName(e.target.value)}
            />
            <Label htmlFor="kb-desc">描述</Label>
            <Input
              id="kb-desc"
              placeholder="描述知识库的用途（可选）"
              value={newKbDesc}
              onChange={(e) => setNewKbDesc(e.target.value)}
            />
          </form>
          <DialogFooter className="space-x-3">
            <Button variant="outline" onClick={() => setShowCreateKb(false)}>
              取消
            </Button>
            <Button onClick={handleCreateKb} disabled={creating} className="btn-primary">
              {creating ? '创建中...' : '创建知识库'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function KnowledgeBaseCard({ kb, onRefresh }: { kb: KnowledgeBase; onRefresh: () => void }) {
  const handleDelete = async () => {
    if (window.confirm('确定要删除这个知识库吗？此操作不可恢复。')) {
      try {
        await api.deleteKnowledgeBase(kb.id);
        onRefresh();
      } catch (error) {
        console.error('Failed to delete KB:', error);
        alert('删除失败，请稍后重试');
      }
    }
  };

  return (
    <Card className="glass hover:shadow-md transition-all group border border-border/50">
      <CardHeader className="pb-4">
        <div className="flex items-start justify-between">
          <div>
            <CardTitle className="text-lg font-semibold text-foreground">{kb.name}</CardTitle>
            <CardDescription className="mt-1">{kb.description || '暂无描述'}</CardDescription>
          </div>
          <Badge variant="secondary" size="sm" className="opacity-50 group-hover:opacity-100">
            {kb.embedding_model || '已就绪'}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-3 gap-4 text-center">
          <div className="p-3 rounded-xl bg-secondary/50">
            <div className="text-2xl font-bold text-primary">{kb.document_count || 0}</div>
            <div className="text-xs text-muted-foreground mt-1">文档</div>
          </div>
          <div className="p-3 rounded-xl bg-secondary/50">
            <div className="text-2xl font-bold text-indigo-600">{kb.chunk_count || 0}</div>
            <div className="text-xs text-muted-foreground mt-1">知识块</div>
          </div>
          <div className="p-3 rounded-xl bg-secondary/50">
            <div className="text-2xl font-bold text-violet-600">{kb.retrieval_final_k || 5}</div>
            <div className="text-xs text-muted-foreground mt-1">Top-K</div>
          </div>
        </div>

        <div className="flex items-center justify-between text-xs text-muted-foreground pt-3 border-t border-border/50">
          <span className="flex items-center gap-1">
            <Activity className="h-3 w-3" />
            {formatRelativeTime(kb.updated_at || kb.created_at)}
          </span>
        </div>

        <div className="flex gap-2 mt-4">
          <Button variant="outline" size="sm" className="flex-1" asChild>
            <a href={`/knowledge-bases/${kb.id}`}>
              <FileText className="mr-2 h-4 w-4" />
              管理文档
            </a>
          </Button>
          <Button variant="outline" size="sm" className="flex-1" asChild>
            <a href={`/chat?kb=${kb.id}`}>
              <MessageSquare className="mr-2 h-4 w-4" />
              开始对话
            </a>
          </Button>
          <Button variant="ghost" size="sm" onClick={handleDelete}>
            <Trash2 className="h-4 w-4 text-destructive" />
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
