// Test fixtures for workflow editor tests
export const mockWorkflow = {
  id: 'test-workflow-1',
  tenant_id: 'test-tenant-1',
  name: 'Test Workflow',
  description: 'A test workflow for unit tests',
  status: 'draft',
  version: 1,
  definition: {
    nodes: [
      { id: 'start-1', type: 'custom', position: { x: 100, y: 100 }, data: { type: 'start', label: '开始', config: {} } },
      { id: 'llm-1', type: 'custom', position: { x: 300, y: 100 }, data: { type: 'llm', label: 'LLM 调用', config: { model: 'gpt-4o-mini', temperature: 0.7, prompt_template: 'Hello {{inputs.name}}' } } },
      { id: 'end-1', type: 'custom', position: { x: 500, y: 100 }, data: { type: 'end', label: '结束', config: {} } },
    ],
    edges: [
      { id: 'e1', source: 'start-1', target: 'llm-1', type: 'smoothstep' },
      { id: 'e2', source: 'llm-1', target: 'end-1', type: 'smoothstep' },
    ],
    viewport: { x: 0, y: 0, zoom: 1 },
  },
  metadata: {},
  created_by: 'test-user-1',
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  published_at: null,
};

export const mockPublishedWorkflow = {
  ...mockWorkflow,
  status: 'published',
  published_at: new Date().toISOString(),
};

export const mockWorkflowsList = [
  mockWorkflow,
  {
    ...mockWorkflow,
    id: 'test-workflow-2',
    name: 'Another Workflow',
    status: 'published',
  },
  {
    ...mockWorkflow,
    id: 'test-workflow-3',
    name: 'Archived Workflow',
    status: 'archived',
  },
];

export const mockKnowledgeBases = [
  { id: 'kb-1', name: '产品手册', description: '产品使用手册', document_count: 10, chunk_count: 150 },
  { id: 'kb-2', name: 'FAQ 常见问题', description: '常见问题解答', document_count: 5, chunk_count: 80 },
  { id: 'kb-3', name: '技术文档', description: '开发者技术文档', document_count: 20, chunk_count: 300 },
];

export const mockModels = [
  { id: 'gpt-4o-mini', object: 'model', created: Date.now(), owned_by: 'openai', context_window: 128000, max_output_tokens: 4096, supports_streaming: true, supports_functions: true, supports_vision: true },
  { id: 'gpt-4o', object: 'model', created: Date.now(), owned_by: 'openai', context_window: 128000, max_output_tokens: 4096, supports_streaming: true, supports_functions: true, supports_vision: true },
  { id: 'claude-3-5-sonnet', object: 'model', created: Date.now(), owned_by: 'anthropic', context_window: 200000, max_output_tokens: 4096, supports_streaming: true, supports_functions: true, supports_vision: true },
  { id: 'claude-3-haiku', object: 'model', created: Date.now(), owned_by: 'anthropic', context_window: 200000, max_output_tokens: 4096, supports_streaming: true, supports_functions: false, supports_vision: false },
];

export const mockValidationResultValid = {
  valid: true,
  errors: [],
  warnings: [],
  node_count: 3,
  edge_count: 2,
};

export const mockValidationResultInvalid = {
  valid: false,
  errors: ['Workflow must have a start node', 'Cycle detected: llm-1 -> rag-1 -> llm-1'],
  warnings: ['No end node found, workflow may not terminate properly'],
  node_count: 3,
  edge_count: 3,
};

export const mockApiResponses = {
  getWorkflows: mockWorkflowsList,
  getWorkflow: mockWorkflow,
  createWorkflow: { id: 'new-workflow-1' },
  updateWorkflow: { success: true },
  deleteWorkflow: { success: true },
  validateWorkflowDefinition: mockValidationResultValid,
  executeWorkflow: { execution_id: 'exec-1', status: 'completed', output: { result: 'Hello World' } },
  getKnowledgeBases: mockKnowledgeBases,
  getModels: { data: mockModels },
};