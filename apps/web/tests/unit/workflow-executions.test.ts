import { describe, it, expect } from 'vitest';
import {
  executionDurationMs,
  executionStatusMeta,
  formatDuration,
  nodeLabel,
  nodeNameMap,
  nodeOutputPreview,
} from '@/lib/workflow-executions';
import type { WorkflowDefinition, WorkflowNodeExecution } from '@/types';

const node = (overrides: Partial<WorkflowNodeExecution> = {}): WorkflowNodeExecution => ({
  node_id: 'llm',
  status: 'completed',
  output: null,
  error: null,
  started_at: '2026-11-26T08:00:00Z',
  completed_at: '2026-11-26T08:00:02Z',
  duration_ms: 2000,
  ...overrides,
});

describe('执行记录展示逻辑', () => {
  it('状态标签大小写不敏感，未知状态原样展示', () => {
    expect(executionStatusMeta('COMPLETED').label).toBe('成功');
    expect(executionStatusMeta('failed').label).toBe('失败');
    expect(executionStatusMeta('RUNNING').label).toBe('执行中');
    expect(executionStatusMeta('weird').label).toBe('weird');
    // 后端历史数据可能没有 status
    expect(executionStatusMeta(null).label).toBe('未知');
  });

  it('耗时按量级切换单位，缺值显示占位符', () => {
    expect(formatDuration(0)).toBe('0 ms');
    expect(formatDuration(820)).toBe('820 ms');
    expect(formatDuration(2000)).toBe('2.0 s');
    expect(formatDuration(65_000)).toBe('1m 5s');
    expect(formatDuration(null)).toBe('—');
    expect(formatDuration(undefined)).toBe('—');
  });

  it('执行耗时用 started_at / completed_at 计算，缺一端返回 null', () => {
    expect(
      executionDurationMs({ started_at: '2026-11-26T08:00:00Z', completed_at: '2026-11-26T08:00:01.500Z' })
    ).toBe(1500);
    expect(executionDurationMs({ started_at: '2026-11-26T08:00:00Z', completed_at: null })).toBeNull();
    expect(executionDurationMs({ started_at: 'not-a-date', completed_at: '2026-11-26T08:00:00Z' })).toBeNull();
  });

  it('节点名从工作流定义里按 node_id 查，查不到退回 id', () => {
    const definition = {
      nodes: [
        { id: 'start', type: 'START', name: '开始', position: { x: 0, y: 0 }, config: {} },
        { id: 'llm', type: 'LLM', name: '生成回答', position: { x: 1, y: 1 }, config: {} },
      ],
      edges: [],
    } satisfies WorkflowDefinition;

    const names = nodeNameMap(definition);
    expect(nodeLabel(node(), names)).toBe('生成回答');
    expect(nodeLabel(node({ node_id: 'gone' }), names)).toBe('gone');
    expect(nodeNameMap(null)).toEqual({});
  });

  it('输出摘要优先取文本字段，否则退回 JSON，并做截断', () => {
    expect(nodeOutputPreview({ content: '你好\n世界' })).toBe('你好 世界');
    expect(nodeOutputPreview({ count: 2, chunks: [] })).toBe('{"count":2,"chunks":[]}');
    expect(nodeOutputPreview(null)).toBe('');
    expect(nodeOutputPreview('x'.repeat(200), 20)).toHaveLength(20);
    expect(nodeOutputPreview('x'.repeat(200), 20).endsWith('…')).toBe(true);
  });
});
