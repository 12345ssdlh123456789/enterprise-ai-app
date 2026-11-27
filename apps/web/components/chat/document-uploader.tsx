'use client';

import { useState, useRef, useCallback } from 'react';
import { useAuth } from '@/lib/auth';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter, DialogDescription } from '@/components/ui/dialog';
import { Progress } from '@/components/ui/progress';
import { Plus, Upload, FileText, Loader2, X, CheckCircle, AlertCircle, ChevronDown, ChevronUp } from 'lucide-react';
import { Document, KnowledgeBase } from '@/types';
import { formatBytes, cn } from '@/lib/utils';

interface UploadFile {
  file: File;
  id: string;
  status: 'pending' | 'uploading' | 'processing' | 'completed' | 'failed';
  progress: number;
  error?: string;
  documentId?: string;
}

export function DocumentUploader({
  knowledgeBase,
  onUploadComplete,
}: {
  knowledgeBase: KnowledgeBase;
  onUploadComplete?: (doc: Document) => void;
}) {
  const { isAuthenticated } = useAuth();
  const [files, setFiles] = useState<UploadFile[]>([]);
  const [showDialog, setShowDialog] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDrag = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      addFiles(Array.from(e.dataTransfer.files));
    }
  }, []);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      addFiles(Array.from(e.target.files));
      e.target.value = '';
    }
  };

  const addFiles = (newFiles: File[]) => {
    const uploadFiles: UploadFile[] = newFiles.map(file => ({
      file,
      id: `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
      status: 'pending',
      progress: 0,
    }));
    setFiles(prev => [...prev, ...uploadFiles]);
    setShowDialog(true);
  };

  const removeFile = (id: string) => {
    setFiles(prev => prev.filter(f => f.id !== id));
  };

  const clearCompleted = () => {
    setFiles(prev => prev.filter(f => f.status !== 'completed'));
  };

  const uploadAll = async () => {
    const pendingFiles = files.filter(f => f.status === 'pending');
    for (const file of pendingFiles) {
      await uploadFile(file.id);
    }
  };

  const uploadFile = async (id: string) => {
    const file = files.find(f => f.id === id);
    if (!file || file.status !== 'pending') return;

    // Update status to uploading
    setFiles(prev => prev.map(f => f.id === id ? { ...f, status: 'uploading', progress: 0 } : f));

    try {
      // 上传到网关（multipart），服务端负责落盘 + 解析 + 分块
      const uploadRes = await api.uploadDocument(file.file, knowledgeBase.id, (progress) => {
        setFiles(prev => prev.map(f => f.id === id ? { ...f, progress } : f));
      });

      const documentId: string = uploadRes?.file_id || uploadRes?.id;
      if (!documentId) {
        throw new Error('上传成功但未返回文档 ID');
      }

      setFiles(prev => prev.map(f => f.id === id ? {
        ...f,
        status: 'completed',
        progress: 100,
        documentId,
      } : f));

      if (onUploadComplete) {
        const doc = await api.getDocument(documentId);
        onUploadComplete(doc);
      }

    } catch (error: any) {
      console.error('Upload failed:', error);
      setFiles(prev => prev.map(f => f.id === id ? {
        ...f,
        status: 'failed',
        error: error.message || '上传失败',
      } : f));
    }
  };

  const retryUpload = (id: string) => {
    setFiles(prev => prev.map(f => f.id === id ? { ...f, status: 'pending', error: undefined, progress: 0 } : f));
    uploadFile(id);
  };

  const getStatusIcon = (status: UploadFile['status']) => {
    switch (status) {
      case 'pending': return <Loader2 className="h-4 w-4 text-muted-foreground animate-spin" />;
      case 'uploading': return <Loader2 className="h-4 w-4 text-primary animate-spin" />;
      case 'processing': return <Loader2 className="h-4 w-4 text-blue-500 animate-spin" />;
      case 'completed': return <CheckCircle className="h-4 w-4 text-green-500" />;
      case 'failed': return <AlertCircle className="h-4 w-4 text-red-500" />;
    }
  };

  const getStatusLabel = (status: UploadFile['status']) => {
    switch (status) {
      case 'pending': return '等待中';
      case 'uploading': return `上传中 ${files.find(f => f.id === files.find(f => f.status === 'uploading')?.id)?.progress || 0}%`;
      case 'processing': return '处理中';
      case 'completed': return '完成';
      case 'failed': return '失败';
    }
  };

  const pendingCount = files.filter(f => f.status === 'pending').length;
  const uploadingCount = files.filter(f => f.status === 'uploading' || f.status === 'processing').length;
  const completedCount = files.filter(f => f.status === 'completed').length;
  const failedCount = files.filter(f => f.status === 'failed').length;

  return (
    <div className="space-y-4">
      {/* Upload Zone */}
      <Card
        className={cn('border-dashed transition-colors', dragActive && 'border-primary bg-primary/5')}
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
        onClick={() => fileInputRef.current?.click()}
      >
        <CardContent className="py-12 text-center">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            onChange={handleFileSelect}
            className="hidden"
            accept=".pdf,.docx,.txt,.md,.html,.csv,.json"
          />
          <Upload className="mx-auto h-12 w-12 text-muted-foreground/50 mb-4" />
          <p className="text-lg font-medium">
            {dragActive ? '释放文件以上传' : '点击或拖拽文件到此处上传'}
          </p>
          <p className="text-sm text-muted-foreground mt-1">
            支持 PDF、DOCX、TXT、Markdown、HTML、CSV、JSON
          </p>
          <p className="text-xs text-muted-foreground mt-2">
            单文件最大 50MB
          </p>
        </CardContent>
      </Card>

      {/* Upload Queue */}
      {(files.length > 0 || showDialog) && (
        <Dialog open={showDialog} onOpenChange={setShowDialog}>
          <DialogContent className="max-w-3xl max-h-[80vh]">
            <DialogHeader>
              <DialogTitle className="flex items-center justify-between">
                <span>上传队列</span>
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <span className="text-green-500">✓ {completedCount}</span>
                  <span className="text-blue-500">⟳ {uploadingCount}</span>
                  <span className="text-red-500">✗ {failedCount}</span>
                  <span className="text-muted-foreground">⏳ {pendingCount}</span>
                </div>
              </DialogTitle>
              <DialogDescription>
                共 {files.length} 个文件
              </DialogDescription>
            </DialogHeader>

            <div className="max-h-[60vh] overflow-y-auto space-y-3">
              {files.map((file) => (
                <UploadFileRow
                  key={file.id}
                  file={file}
                  onRemove={() => removeFile(file.id)}
                  onRetry={() => retryUpload(file.id)}
                  getStatusIcon={getStatusIcon}
                  getStatusLabel={getStatusLabel}
                />
              ))}
            </div>

            <DialogFooter className="flex flex-col sm:flex-row gap-2 w-full">
              {pendingCount > 0 && (
                <Button onClick={uploadAll} className="flex-1">
                  <Upload className="mr-2 h-4 w-4" />
                  开始上传 ({pendingCount})
                </Button>
              )}
              {completedCount > 0 && (
                <Button variant="outline" onClick={clearCompleted} className="flex-1">
                  清除已完成
                </Button>
              )}
              <Button variant="ghost" onClick={() => setShowDialog(false)} className="flex-1">
                关闭
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}

      {/* Quick Upload Button */}
      <Button
        variant="outline"
        onClick={() => fileInputRef.current?.click()}
        className="w-full"
        disabled={!isAuthenticated}
      >
        <Plus className="mr-2 h-4 w-4" />
        选择文件上传
      </Button>
    </div>
  );
}

function UploadFileRow({
  file,
  onRemove,
  onRetry,
  getStatusIcon,
  getStatusLabel,
}: {
  file: UploadFile;
  onRemove: () => void;
  onRetry: () => void;
  getStatusIcon: (status: UploadFile['status']) => React.ReactNode;
  getStatusLabel: (status: UploadFile['status']) => string;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <Card className={cn('overflow-hidden', file.status === 'failed' && 'border-red-200')}>
      <CardContent className="p-3">
        <div className="flex items-center gap-3">
          <div className="flex-shrink-0">
            {getStatusIcon(file.status)}
          </div>

          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between">
              <p className="font-medium truncate">{file.file.name}</p>
              <span className="text-xs text-muted-foreground">{formatBytes(file.file.size)}</span>
            </div>

            <div className="flex items-center gap-2 mt-1">
              <Progress value={file.progress} className="h-1.5 flex-1" />
              <span className="text-xs text-muted-foreground w-20 text-right">
                {getStatusLabel(file.status)}
              </span>
            </div>

            {file.error && (
              <p className="mt-1 text-xs text-red-500">{file.error}</p>
            )}
          </div>

          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={() => setExpanded(!expanded)}
            >
              {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
            </Button>
            {file.status === 'failed' && (
              <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onRetry}>
                <Loader2 className="h-4 w-4" />
              </Button>
            )}
            {(file.status === 'pending' || file.status === 'uploading') && (
              <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onRemove}>
                <X className="h-4 w-4" />
              </Button>
            )}
          </div>
        </div>

        {expanded && (
          <div className="mt-3 pt-3 border-t text-xs text-muted-foreground space-y-1">
            <div>类型: {file.file.type || '未知'}</div>
            <div>大小: {formatBytes(file.file.size)}</div>
            {file.documentId && <div>文档 ID: {file.documentId}</div>}
          </div>
        )}
      </CardContent>
    </Card>
  );
}