'use client';

import { useState, useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useAuth } from '@/lib/auth';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter, DialogDescription } from '@/components/ui/dialog';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { KnowledgeBase, Document } from '@/types';
import { formatDate, formatBytes, formatRelativeTime, cn } from '@/lib/utils';
import { Plus, Search, Upload, FileText, Loader2, Trash2, Edit, ArrowLeft, Settings, ChevronDown, Sliders, Database, Sparkles, CheckCircle2, AlertCircle, Clock } from 'lucide-react';
import { RAGTuner } from '@/components/chat/rag-tuner';
import { toast } from 'sonner';

export default function KnowledgeBaseDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const kbId = params.id as string;

  const [kb, setKb] = useState<KnowledgeBase | null>(null);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [docLoading, setDocLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeTab, setActiveTab] = useState('documents');
  const [showCreateDoc, setShowCreateDoc] = useState(false);
  const [uploading, setUploading] = useState(false);

  // Document form state
  const [docForm, setDocForm] = useState({
    filename: '',
    original_filename: '',
    content_type: '',
    file_size: 0,
    file_hash: '',
  });

  useEffect(() => {
    if (isAuthenticated) {
      loadKb();
      loadDocuments();
    }
  }, [isAuthenticated, kbId]);

  const loadKb = async () => {
    try {
      const data = await api.getKnowledgeBase(kbId);
      setKb(data);
    } catch (error) {
      console.error('Failed to load KB:', error);
      toast.error('加载知识库失败');
      router.push('/');
    }
  };

  const loadDocuments = async () => {
    setDocLoading(true);
    try {
      const data = await api.getDocuments(kbId, { limit: 100 });
      setDocuments(data);
    } catch (error) {
      console.error('Failed to load documents:', error);
      toast.error('加载文档列表失败');
    } finally {
      setDocLoading(false);
      setLoading(false);
    }
  };

  const handleCreateDocument = async () => {
    if (!docForm.filename || !docForm.file_hash) return;
    setUploading(true);
    try {
      await api.createDocument({
        knowledge_base_id: kbId,
        ...docForm,
      });
      setShowCreateDoc(false);
      setDocForm({ filename: '', original_filename: '', content_type: '', file_size: 0, file_hash: '' });
      loadDocuments();
      toast.success('文档添加成功');
    } catch (error) {
      console.error('Failed to create document:', error);
      toast.error('添加文档失败');
    } finally {
      setUploading(false);
    }
  };

  const handleProcessDocument = async (docId: string) => {
    try {
      await api.processDocument(docId, true);
      loadDocuments();
      toast.success('文档处理已提交');
    } catch (error) {
      console.error('Failed to process document:', error);
      toast.error('处理文档失败');
    }
  };

  const handleDeleteDocument = async (docId: string) => {
    if (!confirm('确定要删除这个文档吗？')) return;
    try {
      await api.deleteDocument(docId);
      loadDocuments();
      toast.success('文档已删除');
    } catch (error) {
      console.error('Failed to delete document:', error);
      toast.error('删除文档失败');
    }
  };

  const filteredDocs = documents.filter(doc => {
    // 字段可能缺失，避免 toLowerCase() 抛错导致整页白屏
    const name = (doc.original_filename || doc.filename || doc.title || '').toLowerCase();
    return name.includes(searchQuery.toLowerCase());
  });

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
            <p className="text-sm text-muted-foreground">登录后即可管理知识库</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (!kb) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <Card className="glass max-w-md p-8 text-center border border-border/50">
          <CardHeader>
            <AlertCircle className="mx-auto h-8 w-8 text-muted-foreground mb-4" />
            <CardTitle className="text-lg">知识库不存在</CardTitle>
          </CardHeader>
          <CardContent>
            <Button className="mt-4 btn-primary" onClick={() => router.push('/')}>
              返回首页
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  const totalChunks = documents.reduce((sum, d) => sum + (d.chunk_count || 0), 0);
  const totalTokens = documents.reduce((sum, d) => sum + (d.token_count || 0), 0);

  return (
    <div className="min-h-screen bg-background relative">
      {/* Background decoration */}
      <div className="absolute top-0 right-0 w-72 h-72 bg-violet-500/10 rounded-full blur-3xl -mr-32 -mt-16 pointer-events-none" />
      <div className="absolute bottom-0 left-0 w-72 h-72 bg-sky-500/10 rounded-full blur-3xl -ml-32 -mb-16 pointer-events-none" />

      {/* Header */}
      <header className="border-b bg-card/70 backdrop-blur sticky top-16 z-30 border-border/60">
        <div className="container mx-auto flex h-16 items-center justify-between px-4">
          <div className="flex items-center gap-4">
            <Button variant="ghost" size="icon" onClick={() => router.push('/')}>
              <ArrowLeft className="h-4 w-4" />
            </Button>
            <div className="flex flex-col gap-1">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-xl bg-brand-gradient flex items-center justify-center">
                  <Database className="h-4 w-4 text-white" />
                </div>
                <h1 className="text-xl font-bold text-foreground">{kb.name}</h1>
              </div>
              <p className="text-sm text-muted-foreground truncate max-w-[400px]">
                {kb.description || '暂无描述'}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Tabs value={activeTab} onValueChange={setActiveTab} className="hidden md:flex">
              <TabsList className="gap-1 bg-muted/30 p-1 rounded-xl border border-border/50">
                <TabsTrigger value="documents" className="px-4 py-2 rounded-lg hover:bg-primary/10 transition-colors">
                  <FileText className="mr-2 h-4 w-4" />
                  文档管理
                </TabsTrigger>
                <TabsTrigger value="settings" className="px-4 py-2 rounded-lg hover:bg-primary/10 transition-colors">
                  <Settings className="mr-2 h-4 w-4" />
                  知识库设置
                </TabsTrigger>
              </TabsList>
            </Tabs>

            <Button onClick={() => router.push(`/chat?kb=${kbId}`)} className="flex items-center gap-2 btn-primary">
              <Sparkles className="h-4 w-4" />
              开始对话
            </Button>
          </div>
        </div>

        {/* Search & Stats */}
        <div className="border-t px-4 py-3 bg-card/30 border-border/50 backdrop-blur">
          <div className="flex flex-wrap items-center gap-4">
            <div className="relative flex-1 max-w-md">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder="搜索文档..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-10 input-field h-10"
              />
            </div>
            <div className="flex items-center gap-6 text-sm text-muted-foreground">
              <StatPill label="文档数" value={documents.length} icon={<FileText className="h-4 w-4" />} />
              <StatPill label="分块数" value={totalChunks} icon={<Clock className="h-4 w-4" />} />
              <StatPill label="Token 数" value={totalTokens} icon={<Sparkles className="h-4 w-4" />} />
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="mx-auto w-full max-w-[1360px] p-4 md:p-6">
        {activeTab === 'documents' && (
          <DocumentsTab
            kb={kb}
            documents={filteredDocs}
            loading={docLoading}
            onCreateClick={() => setShowCreateDoc(true)}
            showCreateDoc={showCreateDoc}
            setShowCreateDoc={setShowCreateDoc}
            docForm={docForm}
            setDocForm={setDocForm}
            handleCreateDocument={handleCreateDocument}
            uploading={uploading}
            handleProcessDocument={handleProcessDocument}
            handleDeleteDocument={handleDeleteDocument}
            loadDocuments={loadDocuments}
          />
        )}

        {activeTab === 'settings' && (
          <SettingsTab kb={kb} setKb={setKb} />
        )}
      </main>
    </div>
  );
}

function StatPill({ label, value, icon }: { label: string; value: number | string; icon: React.ReactNode }) {
  return (
    <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-muted/50 border border-border/50">
      {icon}
      <div className="flex flex-col">
        <span className="text-xs text-muted-foreground">{label}</span>
        <span className="text-sm font-semibold text-foreground">{value}</span>
      </div>
    </div>
  );
}

function DocumentsTab({
  kb,
  documents,
  loading,
  onCreateClick,
  showCreateDoc,
  setShowCreateDoc,
  docForm,
  setDocForm,
  handleCreateDocument,
  uploading,
  handleProcessDocument,
  handleDeleteDocument,
  loadDocuments,
}: any) {
  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div className="flex flex-col gap-1">
          <h2 className="text-2xl font-bold text-foreground">文档管理</h2>
          <p className="text-sm text-muted-foreground">管理知识库中的文档，支持添加、处理和删除</p>
        </div>
        <Dialog open={showCreateDoc} onOpenChange={setShowCreateDoc}>
          <DialogTrigger asChild>
            <Button className="btn-primary">
              <Plus className="mr-2 h-4 w-4" />
              添加文档
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-md p-0">
            <DialogHeader className="px-6 py-4">
              <DialogTitle className="text-lg font-bold">添加文档记录</DialogTitle>
              <DialogDescription className="text-sm text-muted-foreground">
                创建文档记录后，可上传文件并处理用于 RAG 检索
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4 p-6">
              <div className="space-y-2">
                <Label htmlFor="doc-filename" className="font-medium text-sm text-foreground">文件名</Label>
                <Input
                  id="doc-filename"
                  placeholder="document.pdf"
                  value={docForm.filename}
                  onChange={(e) => setDocForm({ ...docForm, filename: e.target.value })}
                  className="input-field"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="doc-original" className="font-medium text-sm text-foreground">原始文件名</Label>
                <Input
                  id="doc-original"
                  placeholder="document.pdf"
                  value={docForm.original_filename}
                  onChange={(e) => setDocForm({ ...docForm, original_filename: e.target.value })}
                  className="input-field"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="doc-type" className="font-medium text-sm text-foreground">Content-Type</Label>
                <Input
                  id="doc-type"
                  placeholder="application/pdf"
                  value={docForm.content_type}
                  onChange={(e) => setDocForm({ ...docForm, content_type: e.target.value })}
                  className="input-field"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="doc-size" className="font-medium text-sm text-foreground">文件大小 (bytes)</Label>
                <Input
                  id="doc-size"
                  type="number"
                  placeholder="1024000"
                  value={docForm.file_size}
                  onChange={(e) => setDocForm({ ...docForm, file_size: parseInt(e.target.value) || 0 })}
                  className="input-field"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="doc-hash" className="font-medium text-sm text-foreground">SHA256 哈希</Label>
                <Input
                  id="doc-hash"
                  placeholder="a1b2c3..."
                  value={docForm.file_hash}
                  onChange={(e) => setDocForm({ ...docForm, file_hash: e.target.value })}
                  className="input-field"
                />
              </div>
              <p className="text-xs text-muted-foreground">
                注意：此处仅创建文档记录。实际文件需上传至 MinIO 存储，然后调用处理接口。
              </p>
            </div>
            <DialogFooter className="p-4 border-t border-border/50">
              <Button variant="outline" onClick={() => setShowCreateDoc(false)} className="w-full">
                取消
              </Button>
              <Button onClick={handleCreateDocument} disabled={uploading || !docForm.filename || !docForm.file_hash} className="w-full btn-primary">
                {uploading ? '创建中...' : '创建文档'}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {loading ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 py-12">
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      ) : documents.length === 0 ? (
        <Card className="glass py-16 border border-border/50 flex flex-col items-center justify-center text-center">
          <FileText className="mx-auto h-14 w-14 text-muted-foreground mb-4" />
          <h3 className="text-lg font-medium text-foreground mb-2">暂无文档</h3>
          <p className="text-sm text-muted-foreground mb-6 max-w-md">添加文档并处理后，即可在对话中使用 RAG 检索</p>
          <Button className="btn-primary">
            <Plus className="mr-2 h-4 w-4" />
            添加第一个文档
          </Button>
        </Card>
      ) : (
        <div className="space-y-3">
          {documents.map((doc: Document) => (
            <DocumentRow
              key={doc.id}
              doc={doc}
              onProcess={() => handleProcessDocument(doc.id)}
              onDelete={() => handleDeleteDocument(doc.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function SkeletonCard() {
  return (
    <Card className="animate-pulse glass border border-border/50">
      <CardContent className="h-48 flex flex-col gap-4">
        <div className="h-6 bg-muted rounded w-3/4" />
        <div className="h-4 bg-muted rounded w-1/2" />
        <div className="h-4 bg-muted rounded w-1/3" />
        <div className="h-4 bg-muted rounded w-2/3" />
      </CardContent>
    </Card>
  );
}

function DocumentRow({ doc, onProcess, onDelete }: { doc: Document; onProcess: () => void; onDelete: () => void }) {
  const statusColors: Record<string, string> = {
    pending: 'bg-yellow-100 text-yellow-800 border-yellow-200',
    processing: 'bg-blue-100 text-blue-800 border-blue-200',
    completed: 'bg-green-100 text-green-800 border-green-200',
    failed: 'bg-red-100 text-red-800 border-red-200',
  };

  const statusLabels: Record<string, string> = {
    pending: '待处理',
    processing: '处理中',
    completed: '已完成',
    failed: '处理失败',
  };

  return (
    <Card className="glass hover:border-primary/50 transition-all border border-border/50 group">
      <CardContent className="p-4">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-4 flex-1 min-w-0">
            <div className="flex-shrink-0 w-10 h-10 rounded-xl bg-muted/50 flex items-center justify-center text-muted-foreground">
              <FileText className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <p className="font-medium text-foreground truncate">{doc.original_filename || doc.filename || doc.title}</p>
              <p className="text-sm text-muted-foreground truncate">
                {doc.content_type} • {formatBytes(doc.file_size)} • {formatRelativeTime(doc.created_at)}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <span className={cn('px-2.5 py-1 rounded-full text-xs font-medium border', statusColors[doc.status] || 'border-gray-200 bg-gray-100 text-gray-800')}>
              {statusLabels[doc.status] || doc.status}
            </span>

            {doc.page_count > 0 && (
              <span className="text-sm text-muted-foreground flex items-center gap-1">
                <Clock className="h-3 w-3" />
                {doc.page_count} 页 • {doc.chunk_count} 块
              </span>
            )}

            {(doc.status === 'pending' || doc.status === 'failed') && (
              <Button variant="outline" size="sm" onClick={onProcess} className="h-8">
                {doc.status === 'failed' ? '重新处理' : '处理'}
              </Button>
            )}

            <Button variant="ghost" size="icon" onClick={onDelete} disabled={doc.status === 'processing'} className="h-8 w-8 p-0 group-hover:bg-red-50">
              <Trash2 className="h-4 w-4 text-destructive" />
            </Button>
          </div>
        </div>

        {doc.status === 'failed' && doc.error_message && (
          <div className="mt-3 p-3 rounded-lg bg-red-50 border border-red-100 text-red-700 text-sm">
            <AlertCircle className="h-4 w-4 mr-2" />
            错误: {doc.error_message}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function SettingsTab({
  kb,
  setKb,
}: {
  kb: KnowledgeBase;
  setKb: React.Dispatch<React.SetStateAction<KnowledgeBase | null>>;
}) {
  const [showTuner, setShowTuner] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  const handleSettingsSaved = (settings: any) => {
    setKb(prev => prev ? { ...prev, ...settings } : prev);
    setShowTuner(false);
    toast.success('设置已保存');
  };

  return (
    <div className="space-y-6 max-w-4xl">
      <div className="flex items-center justify-between">
        <div className="flex flex-col gap-1">
          <h2 className="text-2xl font-bold text-foreground">知识库设置</h2>
          <p className="text-sm text-muted-foreground">配置知识库的检索和分块参数</p>
        </div>
        <Button onClick={() => setShowTuner(true)} className="flex items-center gap-2 btn-primary">
          <Sliders className="h-4 w-4" />
          打开 RAG 调优面板
        </Button>
      </div>

      <Card className="glass border border-border/50">
        <CardHeader>
          <CardTitle className="font-bold">基本信息</CardTitle>
          <CardDescription className="text-sm">修改知识库的名称和描述</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="kb-name" className="font-medium text-sm text-foreground">名称</Label>
            <Input
              id="kb-name"
              value={kb.name}
              onChange={(e) => setKb(prev => prev ? { ...prev, name: e.target.value } : prev)}
              className="input-field"
              placeholder="知识库名称"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="kb-desc" className="font-medium text-sm text-foreground">描述</Label>
            <Input
              id="kb-desc"
              value={kb.description || ''}
              onChange={(e) => setKb(prev => prev ? { ...prev, description: e.target.value } : prev)}
              className="input-field"
              placeholder="简要描述知识库的内容和用途"
            />
          </div>
        </CardContent>
        <div className="p-4 border-t border-border/50 flex justify-end">
          <Button
            onClick={() => {
              setIsSaving(true);
              setTimeout(() => {
                setIsSaving(false);
                toast.success('基本信息已更新');
              }, 800);
            }}
            disabled={isSaving}
            className="btn-primary"
          >
            {isSaving ? '保存中...' : '保存基本信息'}
          </Button>
        </div>
      </Card>

      <Card className="glass border border-border/50">
        <CardHeader>
          <CardTitle className="font-bold">快速设置</CardTitle>
          <CardDescription className="text-sm">常用参数快捷修改，完整配置请打开 RAG 调优面板</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <SettingGroup label="知识块大小" description="文本分块大小">
            <Input
              type="number"
              value={kb.chunk_size || 1000}
              onChange={(e) => setKb(prev => prev ? { ...prev, chunk_size: parseInt(e.target.value) || 1000 } : prev)}
              className="input-field"
            />
          </SettingGroup>
          <SettingGroup label="分块重叠" description="分块重叠大小">
            <Input
              type="number"
              value={kb.chunk_overlap || 200}
              onChange={(e) => setKb(prev => prev ? { ...prev, chunk_overlap: parseInt(e.target.value) || 200 } : prev)}
              className="input-field"
            />
          </SettingGroup>
          <SettingGroup label="初始检索条数" description="初始检索数量">
            <Input
              type="number"
              value={kb.retrieval_top_k || 20}
              onChange={(e) => setKb(prev => prev ? { ...prev, retrieval_top_k: parseInt(e.target.value) || 20 } : prev)}
              className="input-field"
            />
          </SettingGroup>
          <SettingGroup label="最终返回条数" description="最终返回数量">
            <Input
              type="number"
              value={kb.retrieval_final_k || 5}
              onChange={(e) => setKb(prev => prev ? { ...prev, retrieval_final_k: parseInt(e.target.value) || 5 } : prev)}
              className="input-field"
            />
          </SettingGroup>
        </CardContent>
      </Card>

      {/* RAG Tuner Modal */}
      <Dialog open={showTuner} onOpenChange={setShowTuner}>
        <DialogContent className="max-w-4xl max-h-[90vh] p-0">
          <RAGTuner
            knowledgeBaseId={kb.id}
            knowledgeBaseName={kb.name}
            onClose={() => setShowTuner(false)}
            onSettingsSaved={handleSettingsSaved}
          />
        </DialogContent>
      </Dialog>
    </div>
  );
}

function SettingGroup({ label, description, children }: { label: string; description?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <div>
        <Label className="font-medium text-sm text-foreground">{label}</Label>
        {description && <p className="text-xs text-muted-foreground">{description}</p>}
      </div>
      {children}
    </div>
  );
}
