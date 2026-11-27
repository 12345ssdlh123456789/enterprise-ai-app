'use client';

import { useState, useRef, useEffect, useCallback, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useAuth } from '@/lib/auth';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import {
  Loader2,
  Send,
  Sparkles,
  ChevronLeft,
  Copy,
  ThumbsUp,
  ThumbsDown,
  MessageSquare,
  X,
  Upload,
  History,
  Plus,
  User,
  Bot,
  Database,
  ChevronDown,
  SquarePen,
} from 'lucide-react';
import { KnowledgeBase, RetrievedChunk } from '@/types';
import { formatRelativeTime, cn } from '@/lib/utils';
import { Markdown } from '@/components/ui/markdown';
import { DocumentUploader } from '@/components/chat/document-uploader';
import { ConversationHistory } from '@/components/chat/conversation-history';

interface ChatMessageUI {
  id: string;
  conversation_id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  tokens: number;
  cost_usd: number;
  metadata: Record<string, any>;
  created_at: string;
  sources?: RetrievedChunk[];
}

const SUGGESTIONS = [
  '总结这个知识库的核心内容',
  '有哪些常见的客户问题？',
  '帮我找一下关于入职流程的说明',
];

function ChatPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { isAuthenticated, isLoading: authLoading } = useAuth();

  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [selectedKbId, setSelectedKbId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessageUI[]>([]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingContent, setStreamingContent] = useState('');
  const [currentSources, setCurrentSources] = useState<RetrievedChunk[]>([]);
  const [showSources, setShowSources] = useState(false);
  const [model, setModel] = useState('qwen2.5-coder:1.5b');
  const [availableModels, setAvailableModels] = useState<{ id: string; name: string }[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [temperature, setTemperature] = useState(0.7);
  const [showHistory, setShowHistory] = useState(false);
  const [showUploader, setShowUploader] = useState(false);
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const streamBufferRef = useRef('');
  // 发送时刚创建的对话无需再从服务端回读，避免把流式中的回答覆盖掉
  const skipLoadRef = useRef(false);

  useEffect(() => {
    if (isAuthenticated) {
      loadKbs();
      loadModels();
    }
  }, [isAuthenticated]);

  const loadKbs = async () => {
    try {
      const data = await api.getKnowledgeBases({ limit: 100 });
      setKbs(data);
      const kbParam = searchParams.get('kb');
      if (kbParam && data.some((kb: KnowledgeBase) => kb.id === kbParam)) {
        setSelectedKbId(kbParam);
      } else if (data.length > 0 && !searchParams.get('conversation')) {
        setSelectedKbId(data[0].id);
      }
    } catch (error) {
      console.error('Failed to load KBs:', error);
    }
  };

  const loadModels = async () => {
    try {
      setModelsLoading(true);
      const data = await api.getModels();
      const models = (Array.isArray(data) ? data : data?.data ?? []).filter(
        (m: any) => m.enabled !== false && (m.capabilities ?? []).some(
          (c: any) => String(c).toUpperCase() === 'CHAT'
        )
      );
      setAvailableModels(models.map((m: any) => ({ id: m.id, name: m.name || m.id })));
      if (!availableModels.length && models.length) {
        setModel(models[0].id);
      }
    } catch (error) {
      console.error('Failed to load models:', error);
    } finally {
      setModelsLoading(false);
    }
  };

  useEffect(() => {
    const convId = searchParams.get('conversation');
    if (convId && isAuthenticated && !skipLoadRef.current) loadConversation(convId);
  }, [searchParams.get('conversation'), isAuthenticated]);

  const loadConversation = async (id: string) => {
    try {
      const data = await api.getConversation(id);
      if (data.messages) {
        setMessages(
          data.messages.map((m: any, i: number) => ({
            id: m.id || `hist-${i}`,
            conversation_id: m.conversation_id || id,
            role: m.role,
            content: m.content,
            tokens: m.tokens || 0,
            cost_usd: m.cost_usd || 0,
            metadata: m.metadata || {},
            created_at: m.created_at || new Date().toISOString(),
          }))
        );
      }
      setSelectedKbId(data.knowledge_base_id ?? null);
      setCurrentConversationId(id);
    } catch (error) {
      console.error('Failed to load conversation:', error);
    }
  };

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, isStreaming, streamingContent, scrollToBottom]);

  // auto-grow composer
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [input]);

  const handleStreamChunk = (chunk: any) => {
    const delta =
      chunk?.choices?.[0]?.delta?.content ??
      (typeof chunk?.delta === 'string' ? chunk.delta : undefined) ??
      (typeof chunk?.content === 'string' ? chunk.content : undefined);
    if (delta) {
      streamBufferRef.current += delta;
      setStreamingContent(streamBufferRef.current);
    }
  };

  const fetchSources = async (query: string, kbId: string) => {
    try {
      const result = await api.search({ query, knowledge_base_id: kbId, top_k: 4 });
      const chunks: RetrievedChunk[] = result?.chunks || result?.results || [];
      if (chunks.length) {
        setCurrentSources(chunks);
        setShowSources(true);
      }
    } catch (error) {
      console.debug('Retrieval unavailable, citations skipped:', error);
    }
  };

  const handleSend = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if ((!input.trim() && !streamingContent) || isLoading) return;

    const content = input.trim();
    setInput('');
    setIsLoading(true);
    setIsStreaming(true);
    streamBufferRef.current = '';
    setStreamingContent('');
    setCurrentSources([]);

    const userMessage: ChatMessageUI = {
      id: `temp-${Date.now()}`,
      conversation_id: currentConversationId || '',
      role: 'user',
      content,
      tokens: 0,
      cost_usd: 0,
      metadata: {},
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMessage]);

    try {
      let conversationId = currentConversationId || searchParams.get('conversation') || undefined;

      if (!conversationId) {
        const newConv = await api.createConversation({
          knowledge_base_id: selectedKbId || undefined,
          title: content.slice(0, 50),
          model,
          temperature,
        });
        const newId: string = newConv.id;
        conversationId = newId;
        setCurrentConversationId(newId);
        skipLoadRef.current = true;
        router.replace(`/chat?conversation=${newId}${selectedKbId ? `&kb=${selectedKbId}` : ''}`);
      }

      await api.streamChatCompletion(
        {
          model,
          messages: [...messages.map((m) => ({ role: m.role, content: m.content })), { role: 'user', content }],
          temperature,
          stream: true,
          conversation_id: conversationId,
          knowledge_base_id: selectedKbId || undefined,
        },
        handleStreamChunk
      );

      const answer = streamBufferRef.current;
      if (answer) {
        setMessages((prev) => [
          ...prev,
          {
            id: `temp-${Date.now() + 1}`,
            conversation_id: conversationId || '',
            role: 'assistant',
            content: answer,
            tokens: 0,
            cost_usd: 0,
            metadata: {},
            created_at: new Date().toISOString(),
          },
        ]);
      }
    } catch (error) {
      console.error('Chat error:', error);
      setMessages((prev) => [
        ...prev.slice(0, -1),
        {
          id: `error-${Date.now()}`,
          conversation_id: currentConversationId || '',
          role: 'assistant',
          content: '抱歉，本次回答失败。请检查模型服务配置后重试。',
          tokens: 0,
          cost_usd: 0,
          metadata: {},
          created_at: new Date().toISOString(),
        },
      ]);
    } finally {
      setIsLoading(false);
      setIsStreaming(false);
      setStreamingContent('');
      skipLoadRef.current = false;
      if (selectedKbId) fetchSources(content, selectedKbId);
    }
  };

  const handleSelectConversation = (id: string) => {
    setCurrentConversationId(id);
    loadConversation(id);
    setShowHistory(false);
  };

  const handleNewConversation = () => {
    setMessages([]);
    setCurrentConversationId(null);
    setCurrentSources([]);
    router.replace('/chat');
    setShowHistory(false);
  };

  const handleCopy = (content: string) => {
    navigator.clipboard.writeText(content);
  };

  if (authLoading) {
    return (
      <div className="flex min-h-[70vh] items-center justify-center">
        <Loader2 className="h-7 w-7 animate-spin text-primary" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div className="flex min-h-[70vh] items-center justify-center px-4">
        <div className="section-card w-full max-w-md p-8 text-center">
          <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-gradient text-white shadow-glow">
            <Bot className="h-7 w-7" />
          </div>
          <h2 className="text-xl font-semibold text-foreground">请先登录</h2>
          <p className="mt-2 text-sm text-muted-foreground">登录后即可使用基于知识库的智能对话助手。</p>
          <Button className="btn-primary mt-6 w-full" onClick={() => router.push('/')}>
            去登录
          </Button>
        </div>
      </div>
    );
  }

  const selectedKb = kbs.find((kb) => kb.id === selectedKbId);

  return (
    <>
      <div className="flex h-[calc(100vh-4rem)] flex-col">
        {/* Header */}
        <header className="flex-none border-b border-border/70 bg-card/60 backdrop-blur">
          <div className="mx-auto flex h-14 w-full max-w-5xl items-center justify-between gap-3 px-4">
            <div className="flex min-w-0 items-center gap-3">
              <Button variant="ghost" size="icon" className="h-8 w-8 rounded-lg" onClick={() => router.push('/')}>
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <div className="flex h-8 w-8 flex-none items-center justify-center rounded-lg bg-brand-gradient text-white">
                <Bot className="h-4 w-4" />
              </div>
              <div className="min-w-0">
                <h1 className="truncate text-sm font-semibold text-foreground">
                  {selectedKb ? selectedKb.name : '智能对话'}
                </h1>
                <p className="truncate text-[11px] text-muted-foreground">
                  {selectedKb ? '基于所选知识库进行检索增强回答' : '选择知识库以启用引用'}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <Select value={selectedKbId || 'none'} onValueChange={(v) => setSelectedKbId(v === 'none' ? null : v)}>
                <SelectTrigger className="h-9 w-[190px] rounded-xl border-border/80 text-sm">
                  <SelectValue placeholder="选择知识库" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">不使用知识库</SelectItem>
                  {kbs.map((kb) => (
                    <SelectItem key={kb.id} value={kb.id}>
                      {kb.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Button variant="outline" size="icon" className="h-9 w-9 rounded-xl" onClick={() => setShowHistory(true)} title="历史对话">
                <History className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </header>

        {/* Messages */}
        <div className="relative flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-3xl px-4 py-6">
            {messages.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16 text-center">
                <div className="mb-5 flex h-16 w-16 items-center justify-center rounded-2xl bg-brand-gradient text-white shadow-glow">
                  <Sparkles className="h-7 w-7" />
                </div>
                <h2 className="text-xl font-semibold text-foreground">有什么可以帮你？</h2>
                <p className="mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">
                  {selectedKb
                    ? `我可以在「${selectedKb.name}」中检索内容，并给出带引用的回答。`
                    : '选择左侧知识库后，回答会结合你的企业文档。'}
                </p>
                <div className="mt-7 flex flex-wrap justify-center gap-2">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      onClick={() => {
                        setInput(s);
                        textareaRef.current?.focus();
                      }}
                      className="rounded-xl border border-border/80 bg-card px-3.5 py-2 text-sm text-muted-foreground shadow-sm transition-all hover:-translate-y-0.5 hover:border-primary/30 hover:text-foreground"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="space-y-6">
                {messages.map((message, index) => (
                  <MessageBubble
                    key={`${message.id}-${index}`}
                    message={message}
                    isStreaming={false}
                    onCopy={() => handleCopy(message.content)}
                    onRetry={() => {
                      setInput(message.content);
                      textareaRef.current?.focus();
                    }}
                  />
                ))}
                {isStreaming && (
                  <MessageBubble
                    message={{
                      id: 'streaming',
                      conversation_id: '',
                      role: 'assistant',
                      content: streamingContent,
                      tokens: 0,
                      cost_usd: 0,
                      metadata: {},
                      created_at: new Date().toISOString(),
                    }}
                    isStreaming
                  />
                )}
                <div ref={messagesEndRef} />
              </div>
            )}
          </div>
        </div>

        {/* Citations */}
        {currentSources.length > 0 && (
          <div className="flex-none border-t border-border/70 bg-muted/30">
            <div className="mx-auto w-full max-w-3xl px-4 py-3">
              <button
                className="flex w-full items-center justify-between text-left"
                onClick={() => setShowSources((v) => !v)}
              >
                <span className="flex items-center gap-2 text-sm font-medium text-foreground">
                  <Database className="h-4 w-4 text-primary" />
                  引用来源
                  <span className="rounded-md bg-primary/10 px-1.5 text-xs font-semibold text-primary">
                    {currentSources.length}
                  </span>
                </span>
                <ChevronDown className={cn('h-4 w-4 text-muted-foreground transition-transform', showSources && 'rotate-180')} />
              </button>
              {showSources && (
                <div className="mt-3 grid gap-2 sm:grid-cols-2">
                  {currentSources.map((source, i) => (
                    <SourceCitation key={source.chunk_id || i} source={source} index={i + 1} />
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Composer */}
        <div className="flex-none border-t border-border/70 bg-background/80 px-4 py-4 backdrop-blur">
          <div className="mx-auto w-full max-w-3xl">
            {selectedKb && (
              <div className="mb-3">
                <button
                  onClick={() => setShowUploader((v) => !v)}
                  className="mb-2 flex items-center gap-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-primary"
                >
                  <Upload className="h-3.5 w-3.5" />
                  {showUploader ? '收起上传面板' : '向该知识库上传文档'}
                </button>
                {showUploader && (
                  <div className="rounded-2xl border border-border/80 bg-card p-4 shadow-soft">
                    <DocumentUploader knowledgeBase={selectedKb} onUploadComplete={() => setShowUploader(false)} />
                  </div>
                )}
              </div>
            )}

            <form onSubmit={handleSend}>
              <div className="rounded-2xl border border-border bg-card shadow-soft transition-shadow focus-within:border-primary/30 focus-within:ring-4 focus-within:ring-primary/10">
                <div className="flex items-end gap-2 px-3 pt-3">
                  <textarea
                    ref={textareaRef}
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        handleSend();
                      }
                    }}
                    placeholder={isLoading ? 'AI 正在输入...' : '输入问题，Enter 发送 · Shift+Enter 换行'}
                    disabled={isLoading}
                    rows={1}
                    className="max-h-[200px] min-h-[44px] flex-1 resize-none bg-transparent px-1.5 py-2 text-sm leading-relaxed outline-none placeholder:text-muted-foreground/80 disabled:opacity-60"
                  />
                  <Button
                    type="submit"
                    size="icon"
                    disabled={isLoading || !input.trim()}
                    className="mb-1.5 h-9 w-9 rounded-xl bg-brand-gradient text-white shadow-sm transition-all hover:shadow-glow disabled:opacity-40"
                    title="发送"
                  >
                    {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                  </Button>
                </div>

                <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border/60 px-3 py-2">
                  <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                    <Select value={model} onValueChange={(v: string) => setModel(v)} disabled={modelsLoading}>
                      <SelectTrigger className="h-9 w-[210px] rounded-xl border-border/80 text-sm">
                        <SelectValue placeholder="选择模型" />
                      </SelectTrigger>
                      <SelectContent>
                        {availableModels.map((m) => (
                          <SelectItem key={m.id} value={m.id}>
                            {m.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <label className="flex items-center gap-1.5">
                      <span>温度</span>
                      <input
                        type="range"
                        min="0"
                        max="2"
                        step="0.1"
                        value={temperature}
                        onChange={(e) => setTemperature(parseFloat(e.target.value))}
                        className="h-1.5 w-20 cursor-pointer accent-primary"
                      />
                      <span className="w-6 font-medium text-foreground">{temperature.toFixed(1)}</span>
                    </label>
                    <label className="flex cursor-pointer select-none items-center gap-1.5">
                      <input
                        type="checkbox"
                        checked={showSources}
                        onChange={(e) => setShowSources(e.target.checked)}
                        className="rounded border-input accent-primary"
                      />
                      显示引用
                    </label>
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={handleNewConversation}
                    className="h-7 gap-1.5 rounded-lg px-2 text-xs"
                  >
                    <SquarePen className="h-3.5 w-3.5" />
                    新对话
                  </Button>
                </div>
              </div>
            </form>
            <p className="mt-2 text-center text-[11px] text-muted-foreground">
              AI 回答可能存在偏差，请结合引用来源核实关键信息。
            </p>
          </div>
        </div>
      </div>

      <ConversationHistory
        selectedKbId={selectedKbId}
        currentConversationId={currentConversationId}
        onSelectConversation={handleSelectConversation}
        onNewConversation={handleNewConversation}
        isOpen={showHistory}
        onClose={() => setShowHistory(false)}
      />
    </>
  );
}

function MessageBubble({
  message,
  isStreaming,
  onCopy,
  onRetry,
}: {
  message: ChatMessageUI;
  isStreaming?: boolean;
  onCopy?: () => void;
  onRetry?: () => void;
}) {
  const isUser = message.role === 'user';

  return (
    <div className={cn('flex gap-3', isUser && 'flex-row-reverse')}>
      <div
        className={cn(
          'mt-0.5 flex h-8 w-8 flex-none items-center justify-center rounded-xl',
          isUser ? 'bg-muted text-muted-foreground' : 'bg-brand-gradient text-white shadow-sm'
        )}
      >
        {isUser ? <User className="h-4 w-4" /> : <Sparkles className="h-4 w-4" />}
      </div>

      <div className={cn('min-w-0 max-w-[85%]', isUser && 'flex flex-col items-end')}>
        <div
          className={cn(
            'px-4 py-3 text-sm leading-relaxed shadow-sm',
            isUser
              ? 'rounded-2xl rounded-tr-md bg-brand-gradient text-white'
              : 'w-full rounded-2xl rounded-tl-md border border-border/80 bg-card text-foreground'
          )}
        >
          <Markdown content={message.content || ' '} />
          {isStreaming && <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse rounded-sm bg-primary align-middle" />}
        </div>

        {!isUser && !isStreaming && (
          <div className="mt-1.5 flex items-center gap-1 text-xs text-muted-foreground">
            <span className="mr-1">{formatRelativeTime(message.created_at)}</span>
            <button
              onClick={() => onCopy?.()}
              className="rounded-md p-1 transition-colors hover:bg-muted hover:text-foreground"
              title="复制"
            >
              <Copy className="h-3.5 w-3.5" />
            </button>
            <button className="rounded-md p-1 transition-colors hover:bg-muted hover:text-foreground" title="有用">
              <ThumbsUp className="h-3.5 w-3.5" />
            </button>
            <button className="rounded-md p-1 transition-colors hover:bg-muted hover:text-foreground" title="没用">
              <ThumbsDown className="h-3.5 w-3.5" />
            </button>
            <button
              onClick={() => onRetry?.()}
              className="rounded-md p-1 transition-colors hover:bg-muted hover:text-foreground"
              title="再次提问"
            >
              <MessageSquare className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function SourceCitation({ source, index }: { source: RetrievedChunk; index: number }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded-xl border border-border/80 bg-card p-3 transition-colors hover:border-primary/30">
      <button className="flex w-full items-start gap-2 text-left" onClick={() => setExpanded((v) => !v)}>
        <span className="flex h-5 w-5 flex-none items-center justify-center rounded-md bg-primary/10 text-[11px] font-semibold text-primary">
          {index}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2">
            <span className="truncate text-xs font-medium text-foreground">{source.document_filename || '文档片段'}</span>
            <span className="flex-none rounded bg-muted px-1.5 text-[10px] font-medium text-muted-foreground">
              {(source.score ?? 0).toFixed(2)}
            </span>
          </span>
          <span className={cn('mt-1 block text-xs leading-relaxed text-muted-foreground', !expanded && 'line-clamp-2')}>
            {source.content}
          </span>
        </span>
      </button>
    </div>
  );
}

export default function ChatPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[70vh] items-center justify-center">
          <Loader2 className="h-7 w-7 animate-spin text-primary" />
        </div>
      }
    >
      <ChatPageContent />
    </Suspense>
  );
}
