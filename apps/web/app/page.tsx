'use client';

import { useAuth } from '@/lib/auth';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import { KnowledgeBase, Conversation } from '@/types';
import { formatRelativeTime } from '@/lib/utils';
import {
  Plus,
  Search,
  Upload,
  Trash2,
  FileText,
  Loader2,
  MessageSquare,
  ShieldCheck,
  Layers,
  Database,
  Sparkles,
  ArrowUpRight,
  Clock,
  ChevronRight,
  CheckCircle2,
  Zap,
} from 'lucide-react';

export default function HomePage() {
  const { user, tenant, isLoading, isAuthenticated } = useAuth();
  const router = useRouter();
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('knowledge-bases');
  const [searchQuery, setSearchQuery] = useState('');
  const [showCreateKb, setShowCreateKb] = useState(false);
  const [newKbName, setNewKbName] = useState('');
  const [newKbDesc, setNewKbDesc] = useState('');
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState('');

  useEffect(() => {
    if (isAuthenticated) {
      fetchData();
    }
  }, [isAuthenticated]);

  const fetchData = async () => {
    try {
      const [kbData, convData] = await Promise.all([
        api.getKnowledgeBases({ limit: 50 }),
        api.getConversations({ limit: 10 }).catch(() => []),
      ]);
      setKbs(kbData);
      setConversations(convData || []);
    } catch (error) {
      console.error('Failed to fetch dashboard data:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateKb = async () => {
    if (!newKbName.trim()) return;
    setCreating(true);
    setCreateError('');
    try {
      await api.createKnowledgeBase({ name: newKbName, description: newKbDesc });
      setShowCreateKb(false);
      setNewKbName('');
      setNewKbDesc('');
      fetchData();
    } catch (error: any) {
      setCreateError(error?.response?.data?.detail || '创建知识库失败');
    } finally {
      setCreating(false);
    }
  };

  const filteredKbs = kbs.filter(
    (kb) =>
      kb.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      kb.description?.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const totalDocuments = kbs.reduce((sum, kb) => sum + (kb.document_count || 0), 0);
  const totalChunks = kbs.reduce((sum, kb) => sum + (kb.chunk_count || 0), 0);

  if (isLoading) {
    return (
      <div className="flex min-h-[70vh] items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="h-7 w-7 animate-spin text-primary" />
          <p className="text-sm text-muted-foreground">正在加载工作区...</p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <LoginScreen />;
  }

  const greeting = (() => {
    const hour = new Date().getHours();
    if (hour < 6) return '夜深了';
    if (hour < 12) return '早上好';
    if (hour < 18) return '下午好';
    return '晚上好';
  })();

  return (
    <main className="page-container">
      {/* Header */}
      <section className="flex flex-col gap-6 pb-8 md:flex-row md:items-end md:justify-between">
        <div className="animate-fade-in-up">
          <div className="mb-3 flex items-center gap-2">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-primary/20 bg-primary/5 px-3 py-1 text-xs font-medium text-primary">
              <Sparkles className="h-3.5 w-3.5" />
              RAG 知识增强已就绪
            </span>
            {tenant?.name && (
              <span className="hidden items-center gap-1.5 rounded-full border border-border/80 bg-card px-3 py-1 text-xs font-medium text-muted-foreground sm:inline-flex">
                <ShieldCheck className="h-3.5 w-3.5" />
                {tenant.name}
              </span>
            )}
          </div>
          <h1 className="text-3xl font-bold text-foreground sm:text-4xl">
            {greeting}，<span className="text-brand-gradient">{user?.full_name || user?.email?.split('@')[0]}</span>
          </h1>
          <p className="mt-2 max-w-xl text-[15px] leading-relaxed text-muted-foreground">
            管理企业知识库、编排检索策略，并让智能助手基于你的私有文档回答问题。
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" asChild className="h-10 rounded-xl">
            <a href="/chat">
              <MessageSquare className="mr-2 h-4 w-4" />
              开始对话
            </a>
          </Button>
          <Button onClick={() => setShowCreateKb(true)} className="btn-primary h-10">
            <Plus className="mr-2 h-4 w-4" />
            新建知识库
          </Button>
        </div>
      </section>

      {/* Stats */}
      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <StatCard
          label="知识库"
          value={kbs.length}
          hint="按业务域组织文档"
          icon={<Database className="h-5 w-5" />}
          tint="bg-indigo-500/10 text-indigo-600"
          accent="from-indigo-500 to-violet-500"
        />
        <StatCard
          label="文档总数"
          value={totalDocuments}
          hint="已完成解析与向量化"
          icon={<FileText className="h-5 w-5" />}
          tint="bg-sky-500/10 text-sky-600"
          accent="from-sky-500 to-cyan-500"
        />
        <StatCard
          label="知识块"
          value={totalChunks}
          hint="可被检索的语义片段"
          icon={<Layers className="h-5 w-5" />}
          tint="bg-violet-500/10 text-violet-600"
          accent="from-violet-500 to-fuchsia-500"
        />
      </section>

      {/* Tabs + toolbar */}
      <section className="mt-9">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <Tabs value={activeTab} onValueChange={setActiveTab}>
            <TabsList className="h-11 rounded-xl border border-border/80 bg-card p-1 shadow-soft">
              <TabsTrigger value="knowledge-bases" className="gap-2 rounded-lg px-4 data-[state=active]:bg-primary/10 data-[state=active]:text-primary">
                <Database className="h-4 w-4" />
                知识库
                <span className="rounded-md bg-muted px-1.5 text-[11px] font-semibold text-muted-foreground">
                  {kbs.length}
                </span>
              </TabsTrigger>
              <TabsTrigger value="conversations" className="gap-2 rounded-lg px-4 data-[state=active]:bg-primary/10 data-[state=active]:text-primary">
                <MessageSquare className="h-4 w-4" />
                最近对话
              </TabsTrigger>
            </TabsList>
          </Tabs>

          {activeTab === 'knowledge-bases' && (
            <div className="relative w-full lg:w-80">
              <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder="搜索知识库名称或描述..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="input-field pl-10"
              />
            </div>
          )}
        </div>
      </section>

      {activeTab === 'knowledge-bases' ? (
        <section className="mt-6">
          {loading ? (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {[0, 1, 2].map((i) => (
                <div key={i} className="section-card h-56 p-6">
                  <div className="skeleton h-4 w-24 rounded" />
                  <div className="skeleton mt-4 h-3 w-full rounded" />
                  <div className="skeleton mt-2 h-3 w-2/3 rounded" />
                  <div className="mt-8 grid grid-cols-3 gap-3">
                    <div className="skeleton h-14 rounded-xl" />
                    <div className="skeleton h-14 rounded-xl" />
                    <div className="skeleton h-14 rounded-xl" />
                  </div>
                </div>
              ))}
            </div>
          ) : filteredKbs.length === 0 ? (
            <EmptyKnowledgeBase
              onCreate={() => setShowCreateKb(true)}
              hasSearch={searchQuery.length > 0 && kbs.length > 0}
            />
          ) : (
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {filteredKbs.map((kb) => (
                <KnowledgeBaseCard key={kb.id} kb={kb} onRefresh={fetchData} />
              ))}
            </div>
          )}
        </section>
      ) : (
        <section className="mt-6">
          {conversations.length === 0 ? (
            <div className="section-card flex flex-col items-center justify-center px-6 py-16 text-center">
              <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-muted text-muted-foreground">
                <MessageSquare className="h-6 w-6" />
              </div>
              <h3 className="text-lg font-semibold text-foreground">还没有对话记录</h3>
              <p className="mt-1 max-w-sm text-sm text-muted-foreground">
                选择一个知识库开始提问，对话会自动保存在这里。
              </p>
              <Button asChild className="btn-primary mt-6">
                <a href="/chat">
                  <Sparkles className="mr-2 h-4 w-4" />
                  开始第一次对话
                </a>
              </Button>
            </div>
          ) : (
            <div className="section-card divide-y divide-border/70 overflow-hidden">
              {conversations.map((conv) => (
                <button
                  key={conv.id}
                  onClick={() => router.push(`/chat?conversation=${conv.id}${conv.knowledge_base_id ? `&kb=${conv.knowledge_base_id}` : ''}`)}
                  className="group flex w-full items-center gap-4 px-5 py-4 text-left transition-colors hover:bg-muted/50"
                >
                  <div className="flex h-10 w-10 flex-none items-center justify-center rounded-xl bg-primary/10 text-primary">
                    <MessageSquare className="h-4 w-4" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-foreground">{conv.title || '未命名对话'}</p>
                    <p className="mt-0.5 flex items-center gap-3 text-xs text-muted-foreground">
                      <span>{conv.message_count || 0} 条消息</span>
                      <span className="flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        {formatRelativeTime(conv.updated_at)}
                      </span>
                      <span className="hidden rounded bg-muted px-1.5 py-0.5 sm:inline">{conv.model}</span>
                    </p>
                  </div>
                  <ChevronRight className="h-4 w-4 flex-none text-muted-foreground transition-transform group-hover:translate-x-0.5" />
                </button>
              ))}
            </div>
          )}
        </section>
      )}

      {/* Create dialog */}
      <Dialog open={showCreateKb} onOpenChange={setShowCreateKb}>
        <DialogContent className="max-w-md gap-0 rounded-2xl p-0">
          <DialogHeader className="border-b border-border/70 px-6 py-5">
            <DialogTitle className="text-lg font-semibold">创建知识库</DialogTitle>
            <DialogDescription className="text-sm text-muted-foreground">
              知识库用于组织同一业务域下的文档，并共享检索与分块策略。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-5 px-6 py-5">
            <div className="space-y-2">
              <Label htmlFor="kb-name">知识库名称</Label>
              <Input
                id="kb-name"
                placeholder="例如：产品手册、客服 FAQ"
                value={newKbName}
                onChange={(e) => setNewKbName(e.target.value)}
                className="input-field"
                autoFocus
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="kb-desc">描述（可选）</Label>
              <Input
                id="kb-desc"
                placeholder="说明这个知识库的用途"
                value={newKbDesc}
                onChange={(e) => setNewKbDesc(e.target.value)}
                className="input-field"
              />
            </div>
            {createError && (
              <div className="rounded-xl border border-destructive/20 bg-destructive/10 px-4 py-3 text-sm text-destructive">
                {createError}
              </div>
            )}
          </div>
          <DialogFooter className="border-t border-border/70 px-6 py-4">
            <Button variant="outline" onClick={() => setShowCreateKb(false)} className="rounded-xl">
              取消
            </Button>
            <Button onClick={handleCreateKb} disabled={creating || !newKbName.trim()} className="btn-primary">
              {creating ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Plus className="mr-2 h-4 w-4" />}
              {creating ? '创建中...' : '创建'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </main>
  );
}

function StatCard({
  label,
  value,
  hint,
  icon,
  tint,
  accent,
}: {
  label: string;
  value: number;
  hint: string;
  icon: React.ReactNode;
  tint: string;
  accent: string;
}) {
  return (
    <div className="stat-card group relative overflow-hidden">
      <div className={`absolute inset-x-0 top-0 h-0.5 bg-gradient-to-r ${accent} opacity-70`} />
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm font-medium text-muted-foreground">{label}</p>
          <p className="mt-2 text-3xl font-bold tracking-tight text-foreground">{value}</p>
          <p className="mt-1 text-xs text-muted-foreground">{hint}</p>
        </div>
        <div className={`flex h-11 w-11 items-center justify-center rounded-xl ${tint}`}>{icon}</div>
      </div>
    </div>
  );
}

function KnowledgeBaseCard({ kb, onRefresh }: { kb: KnowledgeBase; onRefresh: () => void }) {
  const [deleting, setDeleting] = useState(false);

  const handleDelete = async () => {
    if (!window.confirm(`确定要删除知识库「${kb.name}」吗？此操作不可恢复。`)) return;
    setDeleting(true);
    try {
      await api.deleteKnowledgeBase(kb.id);
      onRefresh();
    } catch (error) {
      console.error('Failed to delete KB:', error);
      alert('删除失败，请稍后重试');
    } finally {
      setDeleting(false);
    }
  };

  return (
    <article className="feature-card group flex flex-col">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex h-11 w-11 flex-none items-center justify-center rounded-xl bg-brand-gradient-soft text-primary ring-1 ring-primary/10">
            <Database className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <h3 className="truncate text-base font-semibold text-foreground">{kb.name}</h3>
            <p className="mt-1 line-clamp-2 min-h-[2.5rem] text-sm leading-relaxed text-muted-foreground">
              {kb.description || '暂无描述'}
            </p>
          </div>
        </div>
        <button
          onClick={handleDelete}
          disabled={deleting}
          aria-label="删除知识库"
          className="rounded-lg p-1.5 text-muted-foreground opacity-0 transition-all hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100 disabled:opacity-40"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>

      <div className="mt-5 grid grid-cols-3 gap-2">
        <Metric label="文档" value={kb.document_count || 0} />
        <Metric label="知识块" value={kb.chunk_count || 0} />
        <Metric label="Top-K" value={kb.retrieval_final_k || 5} />
      </div>

      <div className="mt-4 flex items-center justify-between border-t border-border/70 pt-3 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <Clock className="h-3.5 w-3.5" />
          创建于 {formatRelativeTime(kb.updated_at || kb.created_at)}
        </span>
        <span className="flex items-center gap-1 rounded-md bg-muted px-1.5 py-0.5 font-medium">
          <Zap className="h-3 w-3" />
          {kb.visibility === 'PUBLIC' ? '公开' : kb.visibility === 'TENANT' ? '租户共享' : '私有'}
        </span>
      </div>

      <div className="mt-4 flex gap-2">
        <Button variant="outline" size="sm" asChild className="h-9 flex-1 rounded-lg">
          <a href={`/knowledge-bases/${kb.id}`}>
            <FileText className="mr-1.5 h-4 w-4" />
            文档
          </a>
        </Button>
        <Button size="sm" asChild className="h-9 flex-1 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90">
          <a href={`/chat?kb=${kb.id}`}>
            <MessageSquare className="mr-1.5 h-4 w-4" />
            对话
            <ArrowUpRight className="ml-1 h-3.5 w-3.5" />
          </a>
        </Button>
      </div>
    </article>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl border border-border/70 bg-muted/40 px-3 py-2.5 text-center">
      <div className="text-lg font-semibold leading-tight text-foreground">{value}</div>
      <div className="mt-0.5 text-[11px] font-medium text-muted-foreground">{label}</div>
    </div>
  );
}

function EmptyKnowledgeBase({ onCreate, hasSearch }: { onCreate: () => void; hasSearch: boolean }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-border bg-card/60 px-6 py-20 text-center">
      <div className="mb-5 flex h-16 w-16 items-center justify-center rounded-2xl bg-brand-gradient-soft text-primary ring-1 ring-primary/10">
        <Upload className="h-7 w-7" />
      </div>
      <h3 className="text-lg font-semibold text-foreground">{hasSearch ? '没有匹配的知识库' : '创建你的第一个知识库'}</h3>
      <p className="mt-1.5 max-w-md text-sm leading-relaxed text-muted-foreground">
        {hasSearch
          ? '试试其他关键词，或新建一个知识库。'
          : '上传产品文档、FAQ 或内部制度，AI 助手即可基于这些内容回答问题。'}
      </p>
      {!hasSearch && (
        <Button onClick={onCreate} className="btn-primary mt-6">
          <Plus className="mr-2 h-4 w-4" />
          新建知识库
        </Button>
      )}
    </div>
  );
}

function LoginScreen() {
  const { login } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      await login(email, password);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || '登录失败，请检查账号密码');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto grid min-h-[calc(100vh-4rem)] w-full max-w-[1360px] items-center gap-10 px-4 py-10 sm:px-6 lg:grid-cols-2 lg:px-8">
      {/* Brand panel */}
      <div className="relative hidden h-[560px] overflow-hidden rounded-3xl bg-brand-gradient p-10 text-white shadow-glow lg:block">
        <div className="absolute inset-0 bg-grid opacity-[0.12]" />
        <div className="absolute -right-16 -top-16 h-64 w-64 rounded-full bg-white/10 blur-2xl" />
        <div className="absolute -bottom-24 -left-10 h-72 w-72 rounded-full bg-black/10 blur-3xl" />

        <div className="relative flex h-full flex-col">
          <div className="flex items-center gap-2.5">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-white/15 ring-1 ring-white/25">
              <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 2 2 7l10 5 10-5-10-5z" />
                <path d="M2 17l10 5 10-5" />
                <path d="M2 12l10 5 10-5" />
              </svg>
            </div>
            <span className="text-lg font-semibold tracking-tight">智汇 AI 工作台</span>
          </div>

          <div className="mt-auto">
            <h2 className="max-w-sm text-3xl font-bold leading-tight">
              让企业知识
              <br />
              变成可对话的生产力
            </h2>
            <p className="mt-4 max-w-sm text-sm leading-relaxed text-white/80">
              统一的知识库、可调的 RAG 检索策略、可视化工作流编排，一套平台覆盖从文档到答案的全链路。
            </p>
            <div className="mt-8 grid gap-3">
              {[
                { icon: <Database className="h-4 w-4" />, text: '多知识库隔离，文档自动分块与向量化' },
                { icon: <ShieldCheck className="h-4 w-4" />, text: '多租户与角色权限，数据按租户隔离' },
                { icon: <CheckCircle2 className="h-4 w-4" />, text: '引用可溯源，回答附带原文片段' },
              ].map((item) => (
                <div key={item.text} className="flex items-center gap-3 text-sm text-white/90">
                  <span className="flex h-8 w-8 flex-none items-center justify-center rounded-lg bg-white/10 ring-1 ring-white/20">
                    {item.icon}
                  </span>
                  {item.text}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Form */}
      <div className="mx-auto w-full max-w-md">
        <div className="mb-8 lg:hidden">
          <div className="flex items-center gap-2.5">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-gradient text-white shadow-glow">
              <Sparkles className="h-5 w-5" />
            </div>
            <span className="text-lg font-semibold tracking-tight text-foreground">智汇 AI 工作台</span>
          </div>
        </div>

        <div className="section-card p-7 sm:p-8">
          <div className="mb-7">
            <h1 className="text-2xl font-bold text-foreground">登录工作区</h1>
            <p className="mt-1.5 text-sm text-muted-foreground">使用企业邮箱登录，继续管理你的知识库。</p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="space-y-2">
              <Label htmlFor="email">工作邮箱</Label>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                placeholder="you@company.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="input-field"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">密码</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="input-field"
              />
            </div>

            {error && (
              <div className="rounded-xl border border-destructive/20 bg-destructive/10 px-4 py-3 text-sm text-destructive">
                {error}
              </div>
            )}

            <Button
              type="submit"
              size="lg"
              disabled={!email || !password || submitting}
              className="btn-primary h-11 w-full rounded-xl"
            >
              {submitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              {submitting ? '登录中...' : '登录'}
            </Button>
          </form>

          <p className="mt-6 text-center text-xs leading-relaxed text-muted-foreground">
            还没有账号？请联系企业管理员开通，或使用平台的注册接口创建租户。
          </p>
        </div>
      </div>
    </div>
  );
}
