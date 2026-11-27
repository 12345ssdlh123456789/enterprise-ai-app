'use client';

import React, { useState, useCallback, useEffect, useMemo } from 'react';
import {
  Node,
  Edge,
  addEdge,
  Connection,
  ReactFlow,
  Controls,
  Background,
  MiniMap,
  Panel,
  useNodesState,
  useEdgesState,
  OnNodesChange,
  OnEdgesChange,
  OnConnect,
  NodeTypes,
  EdgeTypes,
  Handle,
  Position,
  MarkerType,
  NodeProps,
  useReactFlow,
} from 'reactflow';
import 'reactflow/dist/style.css';

import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import { Save, Plus, Trash2, Copy, Check, X, ChevronDown, Settings, Play, Pause, Square, ChevronLeft, GitBranch, AlertTriangle } from 'lucide-react';
import { api } from '@/lib/api';
import { WorkflowDefinition, WorkflowRead, NodeDefinition, EdgeDefinition } from '@/types';
import { cn, formatRelativeTime } from '@/lib/utils';
import { validateWorkflow as validateWorkflowGraph } from '@/lib/workflow-validation';
import { toast } from 'sonner';

// Node type constants
export const NODE_TYPES = {
  start: '开始',
  end: '结束',
  llm: 'LLM 调用',
  rag: '知识检索',
  condition: '条件分支',
  transform: '数据转换',
  http: 'HTTP 请求',
  delay: '延时',
  parallel: '并行',
  merge: '合并',
} as const;

export type NodeType = keyof typeof NODE_TYPES;

const NODE_COLORS: Record<NodeType, { bg: string; border: string; text: string }> = {
  start: { bg: 'bg-green-50', border: 'border-green-300', text: 'text-green-700' },
  end: { bg: 'bg-red-50', border: 'border-red-300', text: 'text-red-700' },
  llm: { bg: 'bg-purple-50', border: 'border-purple-300', text: 'text-purple-700' },
  rag: { bg: 'bg-blue-50', border: 'border-blue-300', text: 'text-blue-700' },
  condition: { bg: 'bg-orange-50', border: 'border-orange-300', text: 'text-orange-700' },
  transform: { bg: 'bg-yellow-50', border: 'border-yellow-300', text: 'text-yellow-700' },
  http: { bg: 'bg-indigo-50', border: 'border-indigo-300', text: 'text-indigo-700' },
  delay: { bg: 'bg-gray-50', border: 'border-gray-300', text: 'text-gray-700' },
  parallel: { bg: 'bg-pink-50', border: 'border-pink-300', text: 'text-pink-700' },
  merge: { bg: 'bg-teal-50', border: 'border-teal-300', text: 'text-teal-700' },
};

const NODE_ICONS: Record<NodeType, React.ReactNode> = {
  start: <Play className="h-4 w-4" />,
  end: <Square className="h-4 w-4" />,
  llm: <Settings className="h-4 w-4" />,
  rag: <Settings className="h-4 w-4" />,
  condition: <ChevronDown className="h-4 w-4" />,
  transform: <ChevronDown className="h-4 w-4" />,
  http: <Settings className="h-4 w-4" />,
  delay: <Pause className="h-4 w-4" />,
  parallel: <Plus className="h-4 w-4" />,
  merge: <ChevronDown className="h-4 w-4" />,
};

// Custom Node Components
function CustomNode({ id, data, selected }: NodeProps) {
  const { setNodes, setEdges } = useReactFlow();
  const onDelete = () => {
    setNodes((nds) => nds.filter((n) => n.id !== id));
    setEdges((eds) => eds.filter((e) => e.source !== id && e.target !== id));
  };
  // 后端存的是大写类型（START/END/LLM），统一转小写再做比较和配色
  const rawType = String(data.type || 'start').toLowerCase();
  const type = (rawType === 'input' ? 'start' : rawType === 'output' ? 'end' : rawType) as NodeType;
  const colors = NODE_COLORS[type] || NODE_COLORS.start;
  const isStart = type === 'start';
  const isEnd = type === 'end';

  return (
    <div
      className={cn(
        'relative p-3 rounded-lg border-2 transition-all min-w-[180px] max-w-[280px]',
        'shadow-sm',
        selected && 'ring-2 ring-primary ring-offset-2',
        colors.bg,
        colors.border,
        colors.text
      )}
      style={{ userSelect: 'none' }}
    >
      {/* Delete button */}
      <button
        onClick={(e) => { e.stopPropagation(); onDelete(); }}
        className="absolute -top-2 -right-2 p-1 rounded-full bg-red-100 text-red-600 hover:bg-red-200 opacity-0 hover:opacity-100 transition-opacity"
        aria-label="删除节点"
      >
        <X className="h-3 w-3" />
      </button>

      {/* Type badge */}
      <div className="flex items-center gap-2 mb-2">
        <span className="inline-flex items-center justify-center w-6 h-6 rounded bg-white/50 border">
          {NODE_ICONS[type] ?? <Settings className="h-4 w-4" />}
        </span>
        <span className="text-xs font-medium uppercase tracking-wide">{NODE_TYPES[type] ?? type}</span>
        {data.isDefault && <span className="text-xs px-1.5 py-0.5 rounded bg-primary/20 text-primary">默认</span>}
      </div>

      {/* Node content based on type */}
      <div className="space-y-2 text-sm">
        {/* 开始/结束节点的默认名和类型名相同，避免重复显示 */}
        {data.label && data.label !== NODE_TYPES[type] && (
          <div className="font-medium truncate">{data.label}</div>
        )}

        {type === 'llm' && (
          <div className="text-xs opacity-75">
            <div>模型: {data.config?.model || 'gpt-4o-mini'}</div>
            <div>温度: {data.config?.temperature || 0.7}</div>
          </div>
        )}

        {type === 'rag' && (
          <div className="text-xs opacity-75">
            <div>知识库: {data.config?.knowledge_base_id?.slice(0, 8) || '未选择'}</div>
            <div>Top-K: {data.config?.top_k || 5}</div>
          </div>
        )}

        {type === 'condition' && (
          <div className="text-xs opacity-75 font-mono bg-muted/50 px-2 py-1 rounded truncate">
            {data.config?.condition || '条件'}
          </div>
        )}

        {type === 'http' && (
          <div className="text-xs opacity-75">
            <div>{data.config?.method || 'GET'} {data.config?.url || '未配置'}</div>
          </div>
        )}

        {type === 'delay' && (
          <div className="text-xs opacity-75">
            延时: {data.config?.duration_ms || 1000}ms
          </div>
        )}
      </div>

      {/* Handles：必须有唯一 id，否则 React Flow 无法匹配连线，边不会渲染 */}
      {!isStart && (
        <Handle
          id="in"
          type="target"
          position={Position.Left}
          className="w-2 h-2 bg-primary border-2 border-white"
        />
      )}
      {!isEnd && (
        <Handle
          id="out"
          type="source"
          position={Position.Right}
          className="w-2 h-2 bg-primary border-2 border-white"
        />
      )}
    </div>
  );
}

// Node configuration panel
function NodeConfigPanel({
  node,
  onUpdate,
  onClose,
  availableModels,
  availableKnowledgeBases,
}: {
  node: Node | null;
  onUpdate: (config: any) => void;
  onClose: () => void;
  availableModels: string[];
  availableKnowledgeBases: { id: string; name: string }[];
}) {
  if (!node) return null;

  const type = node.data.type as NodeType;
  const config = node.data.config || {};

  const handleChange = (key: string, value: any) => {
    onUpdate({ ...config, [key]: value });
  };

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className="max-w-lg max-h-[85vh]">
        <DialogHeader>
          <DialogTitle>配置节点: {NODE_TYPES[type]}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label>节点标签</Label>
            <Input
              value={node.data.label || ''}
              onChange={(e) => onUpdate({ ...config, label: e.target.value })}
              placeholder="可选，显示在节点上的名称"
            />
          </div>

          {type === 'llm' && (
            <div className="space-y-4">
              <div className="space-y-2">
                <Label>模型</Label>
                <Select value={config.model || 'gpt-4o-mini'} onValueChange={(v: string) => handleChange('model', v)}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {availableModels.map(m => <SelectItem key={m} value={m}>{m}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>提示词模板</Label>
                <Textarea
                  value={config.prompt_template || ''}
                  onChange={(e) => handleChange('prompt_template', e.target.value)}
                  placeholder="使用 {{variable}} 引用上游输出，如：{{inputs.user_question}}"
                  rows={6}
                />
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label>温度</Label>
                  <Input
                    type="number"
                    step="0.1"
                    min="0"
                    max="2"
                    value={config.temperature || 0.7}
                    onChange={(e) => handleChange('temperature', parseFloat(e.target.value))}
                  />
                </div>
                <div className="space-y-2">
                  <Label>最大 Token 数</Label>
                  <Input
                    type="number"
                    value={config.max_tokens || 4096}
                    onChange={(e) => handleChange('max_tokens', parseInt(e.target.value))}
                  />
                </div>
              </div>
            </div>
          )}

          {type === 'rag' && (
            <div className="space-y-4">
              <div className="space-y-2">
                <Label>知识库</Label>
                <Select value={config.knowledge_base_id || ''} onValueChange={(v) => handleChange('knowledge_base_id', v)}>
                  <SelectTrigger><SelectValue placeholder="选择知识库" /></SelectTrigger>
                  <SelectContent>
                    {availableKnowledgeBases.map(kb => <SelectItem key={kb.id} value={kb.id}>{kb.name}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>查询模板</Label>
                <Textarea
                  value={config.query_template || ''}
                  onChange={(e) => handleChange('query_template', e.target.value)}
                  placeholder="如：{{inputs.user_question}}"
                  rows={3}
                />
              </div>
              <div className="grid gap-4 md:grid-cols-3">
                <div className="space-y-2">
                  <Label>检索条数</Label>
                  <Input type="number" value={config.top_k || 5} onChange={(e) => handleChange('top_k', parseInt(e.target.value))} />
                </div>
                <div className="space-y-2">
                  <Label>使用重排序</Label>
                  <div className="flex items-center gap-2">
                    <Switch checked={config.use_rerank !== false} onCheckedChange={(v) => handleChange('use_rerank', v)} />
                  </div>
                </div>
                <div className="space-y-2">
                  <Label>重排 Top K</Label>
                  <Input type="number" value={config.rerank_top_k || 10} onChange={(e) => handleChange('rerank_top_k', parseInt(e.target.value))} />
                </div>
              </div>
            </div>
          )}

          {type === 'condition' && (
            <div className="space-y-4">
              <div className="space-y-2">
                <Label>条件表达式</Label>
                <Textarea
                  value={config.condition || ''}
                  onChange={(e) => handleChange('condition', e.target.value)}
                  placeholder="如：{{inputs.score}} > 0.8"
                  rows={3}
                  className="font-mono"
                />
              </div>
              <p className="text-xs text-muted-foreground">
                支持 JavaScript 表达式，可用变量：上游节点输出、inputs 工作流输入
              </p>
            </div>
          )}

          {type === 'http' && (
            <div className="space-y-4">
              <div className="grid gap-2 md:grid-cols-2">
                <div className="space-y-2">
                  <Label>方法</Label>
                  <Select value={config.method || 'GET'} onValueChange={(v) => handleChange('method', v)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="GET">GET</SelectItem>
                      <SelectItem value="POST">POST</SelectItem>
                      <SelectItem value="PUT">PUT</SelectItem>
                      <SelectItem value="DELETE">DELETE</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>接口地址</Label>
                  <Input value={config.url || ''} onChange={(e) => handleChange('url', e.target.value)} placeholder="https://api.example.com/endpoint" />
                </div>
              </div>
              <div className="space-y-2">
                <Label>请求头 (JSON)</Label>
                <Textarea
                  value={JSON.stringify(config.headers || {}, null, 2)}
                  onChange={(e) => { try { handleChange('headers', JSON.parse(e.target.value)); } catch {} }}
                  rows={4}
                  className="font-mono"
                />
              </div>
              <div className="space-y-2">
                <Label>Body (JSON，可选)</Label>
                <Textarea
                  value={JSON.stringify(config.body || {}, null, 2)}
                  onChange={(e) => { try { handleChange('body', JSON.parse(e.target.value)); } catch {} }}
                  rows={4}
                  className="font-mono"
                />
              </div>
            </div>
          )}

          {type === 'delay' && (
            <div className="space-y-2">
              <Label>延时毫秒数</Label>
              <Input type="number" value={config.duration_ms || 1000} onChange={(e) => handleChange('duration_ms', parseInt(e.target.value))} />
            </div>
          )}

          {type === 'transform' && (
            <div className="space-y-2">
              <Label>转换映射 (JSON)</Label>
              <Textarea
                value={JSON.stringify(config.transform || {}, null, 2)}
                onChange={(e) => { try { handleChange('transform', JSON.parse(e.target.value)); } catch {} }}
                placeholder='{"output_field": "{{inputs.source_field}}"}'
                rows={6}
                className="font-mono"
              />
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>取消</Button>
          <Button onClick={onClose}>完成</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

interface WorkflowEditorProps {
  initialNodes?: any[];
  initialEdges?: any[];
  onSave?: (definition: WorkflowDefinition) => Promise<void> | void;
  onValidate?: (definition: WorkflowDefinition) => Promise<void> | void;
  /** 编辑已有工作流时传入，避免弹“保存工作流”名称框 */
  initialName?: string;
  initialDescription?: string;
  onExecute?: () => Promise<void> | void;
  availableModels?: string[];
  availableKnowledgeBases?: { id: string; name: string }[];
}

// 后端定义里开始/结束节点用 INPUT / OUTPUT，编辑器内部统一用 start / end
function normalizeNodeType(raw: unknown): NodeType {
  const key = String(raw || '').toLowerCase();
  if (key === 'input') return 'start';
  if (key === 'output') return 'end';
  return (key || 'llm') as NodeType;
}

function toFlowNodes(raw: any[] | undefined): Node[] {
  return (raw || []).map((n: any) => ({
    id: n.id,
    type: 'custom',
    position: n.position || { x: 0, y: 0 },
    data: {
      ...(n.data || {}),
      type: normalizeNodeType(n.data?.type || n.type),
      label: n.name || n.label || n.data?.label,
      config: n.config || n.data?.config || {},
    },
  }));
}

function toFlowEdges(raw: any[] | undefined): Edge[] {
  return (raw || []).map((e: any) => ({
    id: e.id,
    source: e.source_node_id ?? e.source,
    target: e.target_node_id ?? e.target,
    sourceHandle: e.source_port_id ?? e.sourceHandle ?? 'out',
    targetHandle: e.target_port_id ?? e.targetHandle ?? 'in',
    type: 'smoothstep',
    animated: true,
    markerEnd: { type: MarkerType.ArrowClosed },
  }));
}

function toDefinition(nodes: Node[], edges: Edge[]): WorkflowDefinition {
  // 后端 WorkflowDefinitionSchema 的字段：name / source_node_id / *_port_id
  return {
    nodes: nodes.map((n) => ({
      id: n.id,
      type: (n.data?.type as string) || 'llm',
      name: (n.data?.label as string) || (n.data?.type as string) || '节点',
      position: n.position,
      config: (n.data?.config as Record<string, any>) || {},
    })),
    edges: edges.map((e) => ({
      id: e.id,
      source_node_id: e.source,
      source_port_id: e.sourceHandle ?? 'out',
      target_node_id: e.target,
      target_port_id: e.targetHandle ?? 'in',
    })),
  };
}

// nodeTypes 必须是稳定引用，否则 React Flow 每次渲染都会重建节点类型
const NODE_TYPES_MAP = { custom: CustomNode };

function WorkflowEditor({
  initialNodes,
  initialEdges,
  onSave,
  onValidate,
  onExecute,
  initialName,
  initialDescription,
  availableModels: modelsProp,
  availableKnowledgeBases: kbsProp,
}: WorkflowEditorProps = {}) {
  const [nodes, setNodes, onNodesChange] = useNodesState(useMemo(() => toFlowNodes(initialNodes), []));
  const [edges, setEdges, onEdgesChange] = useEdgesState(useMemo(() => toFlowEdges(initialEdges), []));
  const [selectedNode, setSelectedNode] = useState<Node | null>(null);
  const [workflowName, setWorkflowName] = useState(initialName || '');
  const [workflowDesc, setWorkflowDesc] = useState(initialDescription || '');
  const [saving, setSaving] = useState(false);
  const [validating, setValidating] = useState(false);
  const [validationResult, setValidationResult] = useState<any>(null);
  const [showConfigPanel, setShowConfigPanel] = useState(false);
  const [availableModels, setAvailableModels] = useState<string[]>(
    modelsProp && modelsProp.length ? modelsProp : ['gpt-4o-mini', 'gpt-4o', 'claude-3-5-sonnet', 'claude-3-haiku'],
  );
  const [availableKnowledgeBases, setAvailableKnowledgeBases] = useState<{ id: string; name: string }[]>(kbsProp || []);

  // Load data
  useEffect(() => {
    loadInitialData();
  }, []);

  const loadInitialData = async () => {
    try {
      const [modelsRes, kbsRes] = await Promise.all([
        api.getModels(),
        api.getKnowledgeBases({ limit: 100 }),
      ]);
      const modelList = Array.isArray(modelsRes) ? modelsRes : modelsRes?.data;
      if (Array.isArray(modelList) && modelList.length) {
        setAvailableModels(modelList.map((m: any) => m.id ?? m.name));
      }
      const kbList = Array.isArray(kbsRes) ? kbsRes : kbsRes?.items;
      if (Array.isArray(kbList) && kbList.length) {
        setAvailableKnowledgeBases(kbList.map((kb: any) => ({ id: kb.id, name: kb.name })));
      }
    } catch (error) {
      console.error('Failed to load initial data:', error);
    }
  };

  const onConnect = useCallback<OnConnect>((params) => {
    setEdges((eds) => addEdge({ ...params, type: 'smoothstep', animated: true, markerEnd: { type: MarkerType.ArrowClosed } }, eds));
  }, []);

  const handleNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelectedNode(node);
    setShowConfigPanel(true);
  }, []);

  const addNode = (type: NodeType) => {
    const newNode: Node = {
      id: `${type}-${Date.now()}`,
      type: 'custom',
      position: { x: 200, y: 100 + nodes.length * 50 },
      data: {
        type,
        label: NODE_TYPES[type],
        config: getDefaultConfig(type),
        isDefault: false,
      },
    };
    setNodes((nds) => [...nds, newNode]);
  };

  const getDefaultConfig = (type: NodeType) => {
    const defaults: Record<NodeType, any> = {
      start: {},
      end: {},
      llm: { model: 'gpt-4o-mini', temperature: 0.7, max_tokens: 4096, prompt_template: '' },
      rag: { top_k: 5, use_rerank: true, rerank_top_k: 10, query_template: '{{inputs.user_question}}' },
      condition: { condition: '' },
      transform: { transform: {} },
      http: { method: 'GET', url: '', headers: {}, body: {} },
      delay: { duration_ms: 1000 },
      parallel: { branches: [] },
      merge: { strategy: 'concat' },
    };
    return defaults[type] || {};
  };

  const deleteNode = (nodeId: string) => {
    setNodes((nds) => nds.filter((n) => n.id !== nodeId));
    setEdges((eds) => eds.filter((e) => e.source !== nodeId && e.target !== nodeId));
    if (selectedNode?.id === nodeId) {
      setSelectedNode(null);
      setShowConfigPanel(false);
    }
  };

  const validateWorkflow = async () => {
    setValidating(true);
    try {
      const definition = toDefinition(nodes, edges);
      // 先本地校验：后端不可用时也能给出错误，无需等网络
      const local = validateWorkflowGraph(nodes, edges);
      if (!local.valid) {
        setValidationResult(local);
        toast.error(`发现 ${local.errors.length} 个错误`);
        return;
      }
      if (onValidate) {
        await onValidate(definition);
        return;
      }
      const result = await api.validateWorkflowDefinition(definition);
      setValidationResult(result);
      if (result.valid) {
        toast.success('验证通过');
      } else {
        toast.error(`发现 ${result.errors.length} 个错误`);
      }
    } catch (error) {
      toast.error('验证失败');
    } finally {
      setValidating(false);
    }
  };

  const saveWorkflow = async () => {
    if (!onSave && !workflowName.trim()) {
      toast.error('请输入工作流名称');
      return;
    }
    setSaving(true);
    try {
      const definition = toDefinition(nodes, edges);
      if (onSave) {
        await onSave(definition);
        toast.success('保存成功');
        return;
      }
      await api.createWorkflow({
        name: workflowName,
        description: workflowDesc,
        definition,
      });
      toast.success('工作流保存成功');
    } catch (error) {
      toast.error('保存失败');
    } finally {
      setSaving(false);
    }
  };

  const executeWorkflow = async () => {
    if (onExecute) {
      await onExecute();
      return;
    }
    if (!workflowName.trim()) {
      toast.error('请先保存工作流');
      return;
    }
    toast.info('执行功能开发中');
  };

  return (
    <div className="flex h-[calc(100vh-4rem)] min-h-[560px] flex-col bg-background">
      {/* Toolbar */}
      <div className="border-b bg-card px-4 py-3 flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <h1 className="text-lg font-semibold">工作流编辑器</h1>
          {validationResult && (
            <Badge variant={validationResult.valid ? 'success' : 'destructive'} className="ml-2">
              {validationResult.valid ? '验证通过' : `${validationResult.errors.length} 个错误`}
            </Badge>
          )}
        </div>

        <div className="flex-1" />

        {/* Node Palette */}
        <div className="flex items-center gap-1 border-l pl-4">
          <span className="text-xs text-muted-foreground">添加节点:</span>
          {(Object.keys(NODE_TYPES) as NodeType[]).map((type) => (
            <Button
              key={type}
              variant="outline"
              size="sm"
              className="h-8 px-2 gap-1"
              onClick={() => addNode(type)}
            >
              {NODE_ICONS[type]}
              <span className="hidden sm:inline">{NODE_TYPES[type]}</span>
            </Button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={validateWorkflow} disabled={validating}>
            <Check className="mr-2 h-4 w-4" />
            验证
          </Button>
          <Button variant="outline" onClick={saveWorkflow} disabled={saving}>
            <Save className="mr-2 h-4 w-4" />
            {saving ? '保存中...' : '保存'}
          </Button>
          <Button onClick={executeWorkflow}>
            <Play className="mr-2 h-4 w-4" />
            执行
          </Button>
        </div>
      </div>

      {/* Main Canvas：flex-1 + 显式 min-h，保证 React Flow 容器有高度 */}
      <div className="relative flex-1 min-h-[420px]">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeClick={handleNodeClick}
          onPaneClick={() => { setSelectedNode(null); setShowConfigPanel(false); }}
          nodeTypes={NODE_TYPES_MAP}
          // 用 React Flow 内置的 smoothstep 边：自定义 edgeTypes 会丢失选中态/箭头，且每次渲染重新创建组件
          fitView
          attributionPosition="bottom-left"
        >
          <Background color="#e2e8f0" gap={16} />
          <Controls />
          <MiniMap
            nodeColor={(node) => {
              const type = node.data?.type as NodeType;
              return NODE_COLORS[type]?.border.replace('border-', '') || '#64748b';
            }}
          />
          <defs>
            <marker id="arrowhead" markerWidth={10} markerHeight={7} refX={9} refY={3.5} orient="auto">
              <path d="M0,0 L0,7 L9,3.5 Z" fill="#64748b" />
            </marker>
          </defs>
        </ReactFlow>

        {/* Validation Errors Panel */}
        {validationResult && !validationResult.valid && (
          <Panel position="bottom-left">
            <div className="p-3 max-w-md">
              <h4 className="font-medium text-red-600 mb-2">验证错误</h4>
              <ul className="space-y-1 text-sm text-red-700">
                {validationResult.errors.map((err: string, i: number) => (
                  <li key={i} className="flex items-center gap-2">
                    <X className="h-3 w-3 flex-shrink-0" />
                    {err}
                  </li>
                ))}
                {validationResult.warnings.map((warn: string, i: number) => (
                  <li key={i} className="flex items-center gap-2 text-orange-600">
                    <AlertTriangle className="h-3 w-3 flex-shrink-0" />
                    {warn}
                  </li>
                ))}
              </ul>
            </div>
          </Panel>
        )}
      </div>

      {/* Config Panel */}
      {showConfigPanel && (
        <Panel position="top-right">
          <NodeConfigPanel
            node={selectedNode}
            onUpdate={(config) => {
              setNodes((nds) => nds.map((n) =>
                n.id === selectedNode?.id ? { ...n, data: { ...n.data, config } } : n
              ));
            }}
            onClose={() => { setShowConfigPanel(false); setSelectedNode(null); }}
            availableModels={availableModels}
            availableKnowledgeBases={availableKnowledgeBases}
          />
        </Panel>
      )}

      {/* Workflow Info Dialog */}
      <Dialog open={!onSave && !workflowName && nodes.length > 0}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>保存工作流</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="wf-name">工作流名称</Label>
              <Input id="wf-name" value={workflowName} onChange={(e) => setWorkflowName(e.target.value)} placeholder="例如：智能客服问答流程" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="wf-desc">描述 (可选)</Label>
              <Textarea id="wf-desc" value={workflowDesc} onChange={(e) => setWorkflowDesc(e.target.value)} placeholder="工作流用途说明" rows={3} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setWorkflowName('')} className="hidden">取消</Button>
            <Button onClick={saveWorkflow} disabled={!workflowName.trim() || saving}>
              {saving ? '保存中...' : '保存工作流'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
export { WorkflowEditor, NODE_COLORS, NODE_ICONS };
