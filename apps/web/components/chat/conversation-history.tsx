'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useAuth } from '@/lib/auth';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from '@/components/ui/dialog';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import { Loader2, MessageSquare, Pencil, Trash2, Pin, PinOff, Search, X, ChevronLeft, ChevronRight, Clock, Edit2, MoreHorizontal } from 'lucide-react';
import { Conversation } from '@/types';
import { formatRelativeTime, cn } from '@/lib/utils';

interface ConversationHistoryProps {
  selectedKbId: string | null;
  currentConversationId: string | null;
  onSelectConversation: (id: string) => void;
  onNewConversation: () => void;
  isOpen: boolean;
  onClose: () => void;
}

export function ConversationHistory({
  selectedKbId,
  currentConversationId,
  onSelectConversation,
  onNewConversation,
  isOpen,
  onClose,
}: ConversationHistoryProps) {
  const { isAuthenticated } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [showRenameDialog, setShowRenameDialog] = useState(false);
  const [renamingConversation, setRenamingConversation] = useState<Conversation | null>(null);
  const [newTitle, setNewTitle] = useState('');
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const loadConversations = useCallback(async () => {
    if (!isAuthenticated) return;
    setLoading(true);
    try {
      const data = await api.getConversations({ limit: 100 });
      // Filter by KB if selected
      const filtered = selectedKbId
        ? data.filter((c: Conversation) => c.knowledge_base_id === selectedKbId)
        : data;
      setConversations(filtered);
    } catch (error) {
      console.error('Failed to load conversations:', error);
    } finally {
      setLoading(false);
    }
  }, [isAuthenticated, selectedKbId]);

  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  // Also reload when KB changes
  useEffect(() => {
    if (selectedKbId) {
      loadConversations();
    }
  }, [selectedKbId, loadConversations]);

  const handleRename = async () => {
    if (!renamingConversation || !newTitle.trim()) return;
    try {
      await api.updateConversation(renamingConversation.id, { title: newTitle });
      setConversations(prev =>
        prev.map(c => c.id === renamingConversation.id ? { ...c, title: newTitle } : c)
      );
      setShowRenameDialog(false);
      setRenamingConversation(null);
      setNewTitle('');
    } catch (error) {
      console.error('Failed to rename conversation:', error);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('确定要删除这个对话吗？此操作不可恢复。')) return;
    try {
      await api.deleteConversation(id);
      setConversations(prev => prev.filter(c => c.id !== id));
      // If deleted current conversation, navigate to new chat
      if (currentConversationId === id) {
        router.push('/chat');
      }
    } catch (error) {
      console.error('Failed to delete conversation:', error);
    } finally {
      setDeletingId(null);
    }
  };

  const handlePin = async (conversation: Conversation) => {
    // TODO: Implement pin/unpin via API
    console.log('Pin conversation:', conversation.id);
  };

  const filteredConversations = conversations.filter(c =>
    c.title.toLowerCase().includes(searchQuery.toLowerCase())
  );

  // Group conversations by date
  const groupedConversations = filteredConversations.reduce((acc, conv) => {
    const date = new Date(conv.updated_at).toDateString();
    if (!acc[date]) acc[date] = [];
    acc[date].push(conv);
    return acc;
  }, {} as Record<string, Conversation[]>);

  const sortedDates = Object.keys(groupedConversations).sort((a, b) =>
    new Date(b).getTime() - new Date(a).getTime()
  );

  const getDateLabel = (dateStr: string) => {
    const date = new Date(dateStr);
    const today = new Date();
    const yesterday = new Date(today);
    yesterday.setDate(yesterday.getDate() - 1);

    if (date.toDateString() === today.toDateString()) return '今天';
    if (date.toDateString() === yesterday.toDateString()) return '昨天';
    return date.toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', year: 'numeric' });
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex flex-col lg:hidden">
      {/* Overlay */}
      <div
        className="fixed inset-0 bg-black/50"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Sidebar */}
      <div className="fixed inset-y-0 left-0 w-80 bg-card shadow-xl flex flex-col animate-slide-in">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b">
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="icon" onClick={onClose} className="lg:hidden">
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <h2 className="text-lg font-semibold">历史记录</h2>
          </div>
          <Button variant="ghost" size="icon" onClick={onNewConversation}>
            <MessageSquare className="h-4 w-4" />
          </Button>
        </div>

        {/* Search */}
        <div className="p-4 border-b">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="搜索对话..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-10"
            />
          </div>
        </div>

        {/* Conversation List */}
        <ScrollArea className="flex-1">
          {loading ? (
            <div className="p-4 space-y-3">
              {[1, 2, 3, 4, 5].map(i => (
                <div key={i} className="h-16 animate-pulse bg-muted rounded" />
              ))}
            </div>
          ) : filteredConversations.length === 0 ? (
            <div className="p-8 text-center text-muted-foreground">
              <MessageSquare className="mx-auto h-12 w-12 mb-3 opacity-50" />
              <p className="text-sm">暂无对话记录</p>
              <Button variant="outline" className="mt-3" onClick={onNewConversation}>
                <MessageSquare className="mr-2 h-4 w-4" />
                新建对话
              </Button>
            </div>
          ) : (
            <div className="p-2 space-y-4">
              {sortedDates.map(date => (
                <div key={date}>
                  <div className="px-2 py-1 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                    {getDateLabel(date)}
                  </div>
                  <div className="space-y-1">
                    {groupedConversations[date].map(conv => (
                      <ConversationItem
                        key={conv.id}
                        conversation={conv}
                        isActive={currentConversationId === conv.id}
                        onClick={() => {
                          onSelectConversation(conv.id);
                          onClose();
                        }}
                        onRename={() => {
                          setRenamingConversation(conv);
                          setNewTitle(conv.title);
                          setShowRenameDialog(true);
                        }}
                        onDelete={() => setDeletingId(conv.id)}
                        onPin={() => handlePin(conv)}
                      />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </ScrollArea>

        {/* Footer */}
        <div className="p-4 border-t">
          <Button variant="outline" className="w-full" onClick={onNewConversation}>
            <MessageSquare className="mr-2 h-4 w-4" />
            新建对话
          </Button>
        </div>
      </div>

      {/* Rename Dialog */}
      <Dialog open={showRenameDialog} onOpenChange={setShowRenameDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>重命名对话</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="conv-title">标题</Label>
              <Input
                id="conv-title"
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
                placeholder="输入新标题"
                autoFocus
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowRenameDialog(false)}>
              取消
            </Button>
            <Button onClick={handleRename} disabled={!newTitle.trim()}>
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation */}
      {deletingId && (
        <Dialog open onOpenChange={() => setDeletingId(null)}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>确认删除</DialogTitle>
            </DialogHeader>
            <p className="py-4">确定要删除这个对话吗？此操作不可恢复。</p>
            <DialogFooter>
              <Button variant="outline" onClick={() => setDeletingId(null)}>
                取消
              </Button>
              <Button variant="destructive" onClick={() => handleDelete(deletingId!)}>
                删除
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}

function ConversationItem({
  conversation,
  isActive,
  onClick,
  onRename,
  onDelete,
  onPin,
}: {
  conversation: Conversation;
  isActive: boolean;
  onClick: () => void;
  onRename: () => void;
  onDelete: () => void;
  onPin: () => void;
}) {
  const [showMenu, setShowMenu] = useState(false);

  return (
    <div className="relative">
      <button
        onClick={onClick}
        className={cn(
          'w-full text-left p-2 rounded-lg transition-colors',
          isActive
            ? 'bg-primary/10 text-primary'
            : 'hover:bg-accent'
        )}
      >
        <div className="flex items-start gap-2">
          <MessageSquare className="h-5 w-5 flex-shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <p className={cn('font-medium truncate', isActive && 'font-semibold')}>
              {conversation.title || '无标题对话'}
            </p>
            <div className="flex items-center gap-2 mt-1 text-xs text-muted-foreground">
              <span className="truncate">{formatRelativeTime(conversation.updated_at)}</span>
              {conversation.message_count > 0 && (
                <>
                  <Separator orientation="vertical" className="h-3" />
                  <span>{conversation.message_count} 条消息</span>
                </>
              )}
              {conversation.total_tokens > 0 && (
                <>
                  <Separator orientation="vertical" className="h-3" />
                  <span>{conversation.total_tokens.toLocaleString()} tokens</span>
                </>
              )}
            </div>
          </div>
        </div>
      </button>

      {/* Context Menu */}
      <div
        className={cn(
          'absolute right-2 top-1/2 -translate-y-1/2 z-10',
          showMenu ? 'block' : 'hidden'
        )}
      >
        <div className="bg-popover border shadow-lg rounded-md p-1 min-w-[160px]">
          <button
            onClick={(e) => { e.stopPropagation(); onRename(); setShowMenu(false); }}
            className="flex items-center gap-2 w-full px-3 py-2 text-sm rounded hover:bg-accent"
          >
            <Edit2 className="h-4 w-4" />
            重命名
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); onPin(); setShowMenu(false); }}
            className="flex items-center gap-2 w-full px-3 py-2 text-sm rounded hover:bg-accent"
          >
            <Pin className="h-4 w-4" />
            置顶
          </button>
          <Separator className="my-1" />
          <button
            onClick={(e) => { e.stopPropagation(); onDelete(); setShowMenu(false); }}
            className="flex items-center gap-2 w-full px-3 py-2 text-sm rounded hover:bg-accent text-destructive"
          >
            <Trash2 className="h-4 w-4" />
            删除
          </button>
        </div>
        {/* Click outside to close */}
        <div
          className="fixed inset-0"
          onClick={() => setShowMenu(false)}
        />
      </div>

      {/* Menu Trigger */}
      <button
        onClick={(e) => { e.stopPropagation(); setShowMenu(!showMenu); }}
        className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded hover:bg-accent opacity-0 group-hover:opacity-100 transition-opacity"
        aria-label="更多选项"
      >
        <MoreHorizontal className="h-4 w-4" />
      </button>
    </div>
  );
}