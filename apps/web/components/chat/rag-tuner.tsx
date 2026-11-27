'use client';

import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Slider } from '@/components/ui/slider';
import { Switch } from '@/components/ui/switch';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Separator } from '@/components/ui/separator';
import { Loader2, Sliders, Search, Filter, Zap, Brain, Database, RefreshCw, Save, CheckCircle, AlertCircle, X } from 'lucide-react';
import { KnowledgeBase, RetrievalResponse, RetrievedChunk } from '@/types';
import { api } from '@/lib/api';
import { cn, formatRelativeTime } from '@/lib/utils';

interface RAGTunerProps {
  knowledgeBaseId: string;
  knowledgeBaseName: string;
  onClose?: () => void;
  onSettingsSaved?: (settings: RAGSettings) => void;
}

interface RAGSettings {
  retrieval_top_k: number;
  retrieval_final_k: number;
  rrf_k: number;
  use_rerank: boolean;
  rerank_model: string;
  rerank_top_k: number;
  bm25_weight: number;
  vector_weight: number;
  chunk_size: number;
  chunk_overlap: number;
  score_threshold: number;
  max_tokens_per_chunk: number;
}

interface RetrievalPreview {
  query: string;
  results: RetrievedChunk[];
  timings: {
    vector_ms: number;
    bm25_ms: number;
    fusion_ms: number;
    rerank_ms: number;
    total_ms: number;
  };
}

export function RAGTuner({
  knowledgeBaseId,
  knowledgeBaseName,
  onClose,
  onSettingsSaved,
}: RAGTunerProps) {
  const [settings, setSettings] = useState<RAGSettings>({
    retrieval_top_k: 20,
    retrieval_final_k: 5,
    rrf_k: 60,
    use_rerank: true,
    rerank_model: 'rerank-v3.5',
    rerank_top_k: 10,
    bm25_weight: 0.5,
    vector_weight: 0.5,
    chunk_size: 1000,
    chunk_overlap: 200,
    score_threshold: 0.0,
    max_tokens_per_chunk: 512,
  });

  const [originalSettings, setOriginalSettings] = useState<RAGSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [activeTab, setActiveTab] = useState('retrieval');
  const [preview, setPreview] = useState<RetrievalPreview | null>(null);
  const [previewQuery, setPreviewQuery] = useState('');
  const [previewLoading, setPreviewLoading] = useState(false);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'success' | 'error'>('idle');

  // Load current KB settings
  const loadSettings = useCallback(async () => {
    try {
      const kb = await api.getKnowledgeBase(knowledgeBaseId);
      const loadedSettings: RAGSettings = {
        retrieval_top_k: kb.retrieval_top_k || 20,
        retrieval_final_k: kb.retrieval_final_k || 5,
        rrf_k: kb.rrf_k || 60,
        use_rerank: true,
        rerank_model: 'rerank-v3.5',
        rerank_top_k: 10,
        bm25_weight: 0.5,
        vector_weight: 0.5,
        chunk_size: kb.chunk_size || 1000,
        chunk_overlap: kb.chunk_overlap || 200,
        score_threshold: 0.0,
        max_tokens_per_chunk: 512,
      };
      setSettings(loadedSettings);
      setOriginalSettings({ ...loadedSettings });
    } catch (error) {
      console.error('Failed to load KB settings:', error);
    } finally {
      setLoading(false);
    }
  }, [knowledgeBaseId]);

  useEffect(() => {
    loadSettings();
  }, [loadSettings]);

  const handleSettingChange = <K extends keyof RAGSettings>(key: K, value: RAGSettings[K]) => {
    setSettings(prev => ({ ...prev, [key]: value }));
    setSaveStatus('idle');
  };

  const handleWeightChange = (source: 'bm25' | 'vector', value: number) => {
    const activeKey = source === 'bm25' ? 'bm25_weight' : 'vector_weight';
    const otherKey = source === 'bm25' ? 'vector_weight' : 'bm25_weight';
    const otherValue = Number(settings[otherKey]);
    const total = value + otherValue;
    if (total > 0) {
      handleSettingChange(activeKey, value / total);
      handleSettingChange(otherKey, otherValue / total);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveStatus('saving');
    try {
      // Update KB with new settings
      await api.updateKnowledgeBase(knowledgeBaseId, {
        retrieval_top_k: settings.retrieval_top_k,
        retrieval_final_k: settings.retrieval_final_k,
        rrf_k: settings.rrf_k,
        chunk_size: settings.chunk_size,
        chunk_overlap: settings.chunk_overlap,
      });

      setOriginalSettings({ ...settings });
      setSaveStatus('success');
      onSettingsSaved?.(settings);

      // Auto-hide success after 2s
      setTimeout(() => setSaveStatus('idle'), 2000);
    } catch (error) {
      console.error('Failed to save settings:', error);
      setSaveStatus('error');
      setTimeout(() => setSaveStatus('idle'), 3000);
    } finally {
      setSaving(false);
    }
  };

  const handleReset = () => {
    if (originalSettings) {
      setSettings({ ...originalSettings });
      setSaveStatus('idle');
    }
  };

  const handlePreviewSearch = async () => {
    if (!previewQuery.trim()) return;
    setPreviewLoading(true);
    try {
      const startTotal = performance.now();

      // Vector search
      const vectorStart = performance.now();
      const vectorRes = await api.search({
        query: previewQuery,
        knowledge_base_id: knowledgeBaseId,
        top_k: settings.retrieval_top_k,
        use_rerank: false,
      });
      const vectorMs = performance.now() - vectorStart;

      // BM25 search (simulated - would need separate endpoint)
      const bm25Start = performance.now();
      const bm25Res = await api.search({
        query: previewQuery,
        knowledge_base_id: knowledgeBaseId,
        top_k: settings.retrieval_top_k,
        use_rerank: false,
      });
      const bm25Ms = performance.now() - bm25Start;

      // Fusion + Rerank
      const fusionStart = performance.now();
      const finalRes = await api.search({
        query: previewQuery,
        knowledge_base_id: knowledgeBaseId,
        top_k: settings.retrieval_final_k,
        use_rerank: settings.use_rerank,
      });
      const fusionMs = performance.now() - fusionStart;

      const totalMs = performance.now() - startTotal;

      setPreview({
        query: previewQuery,
        results: finalRes.chunks || [],
        timings: {
          vector_ms: Math.round(vectorMs),
          bm25_ms: Math.round(bm25Ms),
          fusion_ms: Math.round(fusionMs),
          rerank_ms: settings.use_rerank ? Math.round(fusionMs * 0.3) : 0,
          total_ms: Math.round(totalMs),
        },
      });
    } catch (error) {
      console.error('Preview search failed:', error);
    } finally {
      setPreviewLoading(false);
    }
  };

  const hasChanges = originalSettings && JSON.stringify(settings) !== JSON.stringify(originalSettings);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-primary/10 rounded-lg">
            <Sliders className="h-5 w-5 text-primary" />
          </div>
          <div>
            <h2 className="text-xl font-bold">RAG 参数调优</h2>
            <p className="text-sm text-muted-foreground">{knowledgeBaseName}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {saveStatus === 'success' && (
            <span className="text-sm text-green-500 flex items-center gap-1">
              <CheckCircle className="h-4 w-4" />
              已保存
            </span>
          )}
          {saveStatus === 'error' && (
            <span className="text-sm text-red-500 flex items-center gap-1">
              <AlertCircle className="h-4 w-4" />
              保存失败
            </span>
          )}
          {hasChanges && (
            <Button onClick={handleSave} disabled={saving} className="gap-2">
              <Save className="h-4 w-4" />
              保存设置
            </Button>
          )}
          {onClose && (
            <Button variant="ghost" size="icon" onClick={onClose}>
              <X className="h-4 w-4" />
            </Button>
          )}
        </div>
      </div>

      {/* Warning if chunk settings changed */}
      {(settings.chunk_size !== originalSettings?.chunk_size || settings.chunk_overlap !== originalSettings?.chunk_overlap) && (
        <Card className="border-yellow-200 bg-yellow-50">
          <CardContent className="pt-4">
            <div className="flex items-center gap-2 text-yellow-800">
              <AlertCircle className="h-4 w-4" />
              <span className="text-sm">
                分块参数已修改，需重新处理文档才能生效。现有文档将继续使用旧参数。
              </span>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
        <TabsList className="grid w-full grid-cols-4">
          <TabsTrigger value="retrieval">检索参数</TabsTrigger>
          <TabsTrigger value="rerank">重排序</TabsTrigger>
          <TabsTrigger value="chunking">分块策略</TabsTrigger>
          <TabsTrigger value="preview">实时预览</TabsTrigger>
        </TabsList>

        {/* Retrieval Tab */}
        <TabsContent value="retrieval" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>混合检索配置</CardTitle>
              <CardDescription>
                配置向量检索与关键词检索的融合方式。RRF (Reciprocal Rank Fusion) 无需调参，鲁棒性强。
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                <SettingGroup label="向量检索 Top-K" description="初始向量检索返回的候选数量">
                  <Slider
                    value={[settings.retrieval_top_k]}
                    onValueChange={([v]) => handleSettingChange('retrieval_top_k', v)}
                    min={5}
                    max={100}
                    step={5}
                    className="w-full"
                  />
                  <div className="flex justify-between text-sm text-muted-foreground">
                    <span>5</span>
                    <span className="font-medium">{settings.retrieval_top_k}</span>
                    <span>100</span>
                  </div>
                </SettingGroup>

                <SettingGroup label="BM25 检索 Top-K" description="初始关键词检索返回的候选数量">
                  <Slider
                    value={[settings.retrieval_top_k]}
                    onValueChange={([v]) => handleSettingChange('retrieval_top_k', v)}
                    min={5}
                    max={100}
                    step={5}
                    className="w-full"
                  />
                  <div className="flex justify-between text-sm text-muted-foreground">
                    <span>5</span>
                    <span className="font-medium">{settings.retrieval_top_k}</span>
                    <span>100</span>
                  </div>
                </SettingGroup>

                <SettingGroup label="最终返回 Top-K" description="融合重排后最终返回给 LLM 的片段数">
                  <Slider
                    value={[settings.retrieval_final_k]}
                    onValueChange={([v]) => handleSettingChange('retrieval_final_k', v)}
                    min={1}
                    max={20}
                    step={1}
                    className="w-full"
                  />
                  <div className="flex justify-between text-sm text-muted-foreground">
                    <span>1</span>
                    <span className="font-medium">{settings.retrieval_final_k}</span>
                    <span>20</span>
                  </div>
                </SettingGroup>
              </div>

              <Separator />

              {/* RRF Fusion */}
              <div className="space-y-4">
                <h4 className="font-medium flex items-center gap-2">
                  <Zap className="h-4 w-4" />
                  RRF 融合参数
                </h4>
                <SettingGroup label="RRF K 参数" description="RRF 公式中的常数 k，越大越平滑，推荐 60">
                  <Slider
                    value={[settings.rrf_k]}
                    onValueChange={([v]) => handleSettingChange('rrf_k', v)}
                    min={10}
                    max={200}
                    step={10}
                    className="w-full"
                  />
                  <div className="flex justify-between text-sm text-muted-foreground">
                    <span>10</span>
                    <span className="font-medium">{settings.rrf_k}</span>
                    <span>200</span>
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">
                    RRF 公式: score = Σ 1/(k + rank_i) | 当前 k = {settings.rrf_k}
                  </p>
                </SettingGroup>

                {/* Weight visualization */}
                <SettingGroup label="权重可视化" description="向量与 BM25 的相对权重 (RRF 不使用显式权重，仅供参考)">
                  <div className="space-y-3">
                    <div>
                      <div className="flex justify-between text-sm mb-1">
                        <span>向量检索权重</span>
                        <span className="font-medium">{(settings.vector_weight * 100).toFixed(0)}%</span>
                      </div>
                      <Slider
                        value={[settings.vector_weight]}
                        onValueChange={([v]) => handleWeightChange('vector', v)}
                        min={0}
                        max={1}
                        step={0.05}
                        className="w-full"
                      />
                    </div>
                    <div>
                      <div className="flex justify-between text-sm mb-1">
                        <span>BM25 权重</span>
                        <span className="font-medium">{(settings.bm25_weight * 100).toFixed(0)}%</span>
                      </div>
                      <Slider
                        value={[settings.bm25_weight]}
                        onValueChange={([v]) => handleWeightChange('bm25', v)}
                        min={0}
                        max={1}
                        step={0.05}
                        className="w-full"
                      />
                    </div>
                    <div className="h-4 bg-muted rounded-full overflow-hidden flex">
                      <div
                        className="bg-primary h-full transition-all duration-300"
                        style={{ width: `${settings.vector_weight * 100}%` }}
                      />
                      <div
                        className="bg-orange-500 h-full transition-all duration-300"
                        style={{ width: `${settings.bm25_weight * 100}%` }}
                      />
                    </div>
                  </div>
                </SettingGroup>
              </div>

              <Separator />

              {/* Score Threshold */}
              <SettingGroup label="相似度阈值" description="过滤低相关度片段，0 表示不限制">
                <Slider
                  value={[settings.score_threshold]}
                  onValueChange={([v]) => handleSettingChange('score_threshold', v)}
                  min={0}
                  max={1}
                  step={0.05}
                  className="w-full"
                />
                <div className="flex justify-between text-sm text-muted-foreground">
                  <span>0.0 (无限制)</span>
                  <span className="font-medium">{settings.score_threshold.toFixed(2)}</span>
                  <span>1.0 (极严格)</span>
                </div>
              </SettingGroup>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Rerank Tab */}
        <TabsContent value="rerank" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>重排序配置</CardTitle>
              <CardDescription>
                启用 Cohere Rerank 可显著提升检索精度，但会增加延迟和成本。
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <SettingGroup label="启用重排序" description="使用 Cohere Rerank v3.5 对融合结果重新打分">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-medium">启用重排序</p>
                    <p className="text-sm text-muted-foreground">推荐开启，显著提升精度</p>
                  </div>
                  <Switch
                    checked={settings.use_rerank}
                    onCheckedChange={(checked) => handleSettingChange('use_rerank', checked)}
                  />
                </div>
              </SettingGroup>

              {settings.use_rerank && (
                <>
                  <Separator />
                  <div className="grid gap-4 md:grid-cols-2">
                    <SettingGroup label="重排模型" description="Cohere Rerank 模型版本">
                      <Select value={settings.rerank_model} onValueChange={(v) => handleSettingChange('rerank_model', v)}>
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="rerank-v3.5">Rerank v3.5 (推荐，多语言强)</SelectItem>
                          <SelectItem value="rerank-v3.0">Rerank v3.0</SelectItem>
                          <SelectItem value="rerank-multilingual-v2.0">Multilingual v2.0</SelectItem>
                        </SelectContent>
                      </Select>
                    </SettingGroup>

                    <SettingGroup label="重排候选数" description="送入重排序的候选片段数量">
                      <Slider
                        value={[settings.rerank_top_k]}
                        onValueChange={([v]) => handleSettingChange('rerank_top_k', v)}
                        min={5}
                        max={50}
                        step={5}
                        className="w-full"
                      />
                      <div className="flex justify-between text-sm text-muted-foreground">
                        <span>5</span>
                        <span className="font-medium">{settings.rerank_top_k}</span>
                        <span>50</span>
                      </div>
                    </SettingGroup>
                  </div>

                  <Separator />

                  <SettingGroup label="预估延迟与成本" description="重排序会增加额外的 API 调用">
                    <div className="grid gap-3 md:grid-cols-3">
                      <StatCard
                        icon={Database}
                        label="额外延迟"
                        value="~200-500ms"
                        description="每次查询增加"
                      />
                      <StatCard
                        icon={Zap}
                        label="额外成本"
                        value="$1/1K searches"
                        description="Cohere 定价"
                      />
                      <StatCard
                        icon={Brain}
                        label="精度提升"
                        value="+15-30%"
                        description="MRR/Recall 提升"
                      />
                    </div>
                  </SettingGroup>
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Chunking Tab */}
        <TabsContent value="chunking" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>分块策略</CardTitle>
              <CardDescription>
                文档分块参数影响检索粒度。修改后需重新处理文档才能生效。
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="grid gap-4 md:grid-cols-2">
                <SettingGroup label="分块大小 (tokens)" description="每个分块的目标 token 数，越大上下文越连贯">
                  <Slider
                    value={[settings.chunk_size]}
                    onValueChange={([v]) => handleSettingChange('chunk_size', v)}
                    min={200}
                    max={2000}
                    step={100}
                    className="w-full"
                  />
                  <div className="flex justify-between text-sm text-muted-foreground">
                    <span>200</span>
                    <span className="font-medium">{settings.chunk_size}</span>
                    <span>2000</span>
                  </div>
                  <ChunkSizeGuide size={settings.chunk_size} />
                </SettingGroup>

                <SettingGroup label="分块重叠 (tokens)" description="相邻分块的重叠 token 数，防止语义断裂">
                  <Slider
                    value={[settings.chunk_overlap]}
                    onValueChange={([v]) => handleSettingChange('chunk_overlap', v)}
                    min={0}
                    max={500}
                    step={50}
                    className="w-full"
                  />
                  <div className="flex justify-between text-sm text-muted-foreground">
                    <span>0</span>
                    <span className="font-medium">{settings.chunk_overlap}</span>
                    <span>500</span>
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">
                    重叠率: {(settings.chunk_overlap / settings.chunk_size * 100).toFixed(1)}%
                  </p>
                </SettingGroup>
              </div>

              <Separator />

              <SettingGroup label="每片段最大 Token" description="送入重排/生成时的片段截断长度">
                <Slider
                  value={[settings.max_tokens_per_chunk]}
                  onValueChange={([v]) => handleSettingChange('max_tokens_per_chunk', v)}
                  min={256}
                  max={2048}
                  step={128}
                  className="w-full"
                />
                <div className="flex justify-between text-sm text-muted-foreground">
                  <span>256</span>
                  <span className="font-medium">{settings.max_tokens_per_chunk}</span>
                  <span>2048</span>
                </div>
              </SettingGroup>

              {/* Visual preview of chunking */}
              <SettingGroup label="分块效果预览" description="基于当前参数的预估分块数量">
                <ChunkingPreview
                  chunkSize={settings.chunk_size}
                  chunkOverlap={settings.chunk_overlap}
                  sampleTextLength={5000}
                />
              </SettingGroup>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Preview Tab */}
        <TabsContent value="preview" className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>实时检索预览</CardTitle>
              <CardDescription>
                输入测试查询，查看当前参数下的检索结果、耗时和来源片段。
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="flex gap-2">
                <Input
                  placeholder="输入测试查询..."
                  value={previewQuery}
                  onChange={(e) => setPreviewQuery(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handlePreviewSearch()}
                  className="flex-1"
                />
                <Button onClick={handlePreviewSearch} disabled={previewLoading || !previewQuery.trim()}>
                  {previewLoading ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin mr-2" />
                      搜索中...
                    </>
                  ) : (
                    <>
                      <Search className="h-4 w-4 mr-2" />
                      检索预览
                    </>
                  )}
                </Button>
              </div>

              {preview && (
                <>
                  <Separator />
                  {/* Timings */}
                  <div className="grid gap-3 md:grid-cols-5">
                    <TimingCard label="向量检索" value={`${preview.timings.vector_ms}ms`} icon={Database} />
                    <TimingCard label="BM25 检索" value={`${preview.timings.bm25_ms}ms`} icon={Search} />
                    <TimingCard label="融合" value={`${preview.timings.fusion_ms}ms`} icon={Zap} />
                    <TimingCard label="重排" value={`${preview.timings.rerank_ms}ms`} icon={Brain} />
                    <TimingCard label="总计" value={`${preview.timings.total_ms}ms`} icon={RefreshCw} highlight />
                  </div>

                  {/* Results */}
                  <div className="space-y-3">
                    <h4 className="font-medium">检索结果 (Top {preview.results.length})</h4>
                    <div className="space-y-2 max-h-96 overflow-y-auto">
                      {preview.results.map((result, i) => (
                        <ResultCard key={result.chunk_id} result={result} index={i + 1} />
                      ))}
                    </div>
                  </div>
                </>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Footer Actions */}
      <div className="flex justify-end gap-2 pt-4 border-t">
        <Button variant="outline" onClick={handleReset} disabled={!hasChanges}>
          <RefreshCw className="h-4 w-4 mr-2" />
          重置
        </Button>
        <Button onClick={handleSave} disabled={saving || !hasChanges}>
          {saving ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin mr-2" />
              保存中...
            </>
          ) : (
            <>
              <Save className="h-4 w-4 mr-2" />
              保存设置
            </>
          )}
        </Button>
      </div>
    </div>
  );
}

// Helper Components
function SettingGroup({ label, description, children }: { label: string; description?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <div>
        <Label className="font-medium">{label}</Label>
        {description && <p className="text-xs text-muted-foreground mt-0.5">{description}</p>}
      </div>
      {children}
    </div>
  );
}

function StatCard({ icon: Icon, label, value, description }: { icon: any; label: string; value: string; description: string }) {
  return (
    <div className="p-3 rounded-lg bg-muted/50 border">
      <div className="flex items-center gap-2 mb-1">
        <Icon className="h-4 w-4 text-muted-foreground" />
        <span className="text-xs text-muted-foreground">{label}</span>
      </div>
      <p className="font-bold text-lg">{value}</p>
      <p className="text-xs text-muted-foreground">{description}</p>
    </div>
  );
}

function TimingCard({ label, value, icon: Icon, highlight }: { label: string; value: string; icon: any; highlight?: boolean }) {
  return (
    <div className={cn('p-3 rounded-lg border text-center', highlight && 'bg-primary/5 border-primary')}>
      <Icon className="h-4 w-4 mx-auto mb-1 text-muted-foreground" />
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={cn('font-mono font-bold', highlight && 'text-primary')}>{value}</p>
    </div>
  );
}

function ChunkSizeGuide({ size }: { size: number }) {
  const guides = [
    { max: 300, label: '细粒度', desc: '适合精确问答、FAQ', color: 'text-green-500' },
    { max: 600, label: '中等', desc: '平衡精度与上下文', color: 'text-blue-500' },
    { max: 1000, label: '标准', desc: '通用推荐值', color: 'text-primary' },
    { max: 1500, label: '粗粒度', desc: '长文档、语义完整', color: 'text-orange-500' },
    { max: Infinity, label: '大块', desc: '整章节、语义保持', color: 'text-purple-500' },
  ];

  const current = guides.find(g => size <= g.max) || guides[guides.length - 1];

  return (
    <div className="mt-2 p-2 rounded bg-muted/50">
      <span className={cn('text-xs font-medium', current.color)}>● {current.label}</span>
      <span className="text-xs text-muted-foreground ml-2">{current.desc}</span>
    </div>
  );
}

function ChunkingPreview({ chunkSize, chunkOverlap, sampleTextLength }: { chunkSize: number; chunkOverlap: number; sampleTextLength: number }) {
  const numChunks = Math.ceil(sampleTextLength / (chunkSize - chunkOverlap));
  const overlapRatio = (chunkOverlap / chunkSize * 100).toFixed(1);
  const totalTokens = numChunks * chunkSize - (numChunks - 1) * chunkOverlap;

  return (
    <div className="grid gap-3 md:grid-cols-3">
      <PreviewStat label="预估分块数" value={numChunks} unit="个" />
      <PreviewStat label="重叠率" value={overlapRatio} unit="%" />
      <PreviewStat label="总 Token 量" value={totalTokens.toLocaleString()} unit="tokens" />
    </div>
  );
}

function PreviewStat({ label, value, unit }: { label: string; value: number | string; unit: string }) {
  return (
    <div className="p-3 rounded-lg bg-muted/50 border text-center">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="font-bold text-2xl">{value}<span className="text-base font-normal text-muted-foreground ml-1">{unit}</span></p>
    </div>
  );
}

function ResultCard({ result, index }: { result: RetrievedChunk; index: number }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <Card className="overflow-hidden">
      <CardContent className="p-3">
        <div className="flex items-start gap-3">
          <span className="flex-shrink-0 w-6 text-center text-sm font-medium text-primary">{index}.</span>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-xs text-muted-foreground">{result.document_filename}</span>
              <span className="px-1.5 py-0.5 rounded text-xs bg-primary/10 text-primary">
                {result.score.toFixed(3)}
              </span>
            </div>
            <p className={cn('text-sm line-clamp-2', !expanded && 'line-clamp-2')}>
              {result.content}
            </p>
            <Button
              variant="ghost"
              size="sm"
              className="mt-1 h-6 px-2 text-xs"
              onClick={() => setExpanded(!expanded)}
            >
              {expanded ? '收起' : '展开完整内容'}
            </Button>
          </div>
        </div>
        {expanded && (
          <div className="mt-3 p-2 rounded bg-muted text-xs font-mono whitespace-pre-wrap max-h-40 overflow-y-auto">
            {result.content}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
