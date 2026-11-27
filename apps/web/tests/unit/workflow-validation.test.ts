import { describe, it, expect } from 'vitest';
import { validateWorkflow } from '@/lib/workflow-validation';

describe('Workflow Validation', () => {
  const createNode = (id: string, type: string, data: any = {}) => ({
    id,
    type: 'custom',
    position: { x: 0, y: 0 },
    data: { type, label: type, ...data },
  });

  const createEdge = (id: string, source: string, target: string) => ({
    id,
    source,
    target,
    type: 'smoothstep',
  });

  describe('Basic validation', () => {
    it('passes with valid simple workflow', () => {
      const nodes = [
        createNode('start-1', 'start'),
        createNode('llm-1', 'llm'),
        createNode('end-1', 'end'),
      ];
      const edges = [
        createEdge('e1', 'start-1', 'llm-1'),
        createEdge('e2', 'llm-1', 'end-1'),
      ];

      const result = validateWorkflow(nodes, edges);
      expect(result.valid).toBe(true);
      expect(result.errors).toHaveLength(0);
    });

    it('fails with no nodes', () => {
      const result = validateWorkflow([], []);
      expect(result.valid).toBe(false);
      expect(result.errors).toContain('Workflow must have at least one node');
    });

    it('fails with no start node', () => {
      const nodes = [
        createNode('llm-1', 'llm'),
        createNode('end-1', 'end'),
      ];
      const edges = [createEdge('e1', 'llm-1', 'end-1')];

      const result = validateWorkflow(nodes, edges);
      expect(result.valid).toBe(false);
      expect(result.errors).toContain('Workflow must have a start node');
    });

    it('warns with multiple start nodes', () => {
      const nodes = [
        createNode('start-1', 'start'),
        createNode('start-2', 'start'),
        createNode('end-1', 'end'),
      ];
      const edges = [
        createEdge('e1', 'start-1', 'end-1'),
        createEdge('e2', 'start-2', 'end-1'),
      ];

      const result = validateWorkflow(nodes, edges);
      expect(result.valid).toBe(true);
      expect(result.warnings).toContain('Multiple start nodes found, only first will be used');
    });

    it('warns with no end node', () => {
      const nodes = [
        createNode('start-1', 'start'),
        createNode('llm-1', 'llm'),
      ];
      const edges = [createEdge('e1', 'start-1', 'llm-1')];

      const result = validateWorkflow(nodes, edges);
      expect(result.valid).toBe(true);
      expect(result.warnings).toContain('No end node found, workflow may not terminate properly');
    });
  });

  describe('Orphan node detection', () => {
    it('warns about orphan nodes', () => {
      const nodes = [
        createNode('start-1', 'start'),
        createNode('llm-1', 'llm'),
        createNode('rag-1', 'rag'), // orphan
        createNode('end-1', 'end'),
      ];
      const edges = [
        createEdge('e1', 'start-1', 'llm-1'),
        createEdge('e2', 'llm-1', 'end-1'),
        // rag-1 not connected
      ];

      const result = validateWorkflow(nodes, edges);
      expect(result.valid).toBe(true);
      expect(result.warnings).toContain('1 orphan nodes not connected to any edge');
    });

    it('does not warn for connected nodes', () => {
      const nodes = [
        createNode('start-1', 'start'),
        createNode('llm-1', 'llm'),
        createNode('rag-1', 'rag'),
        createNode('end-1', 'end'),
      ];
      const edges = [
        createEdge('e1', 'start-1', 'llm-1'),
        createEdge('e2', 'llm-1', 'rag-1'),
        createEdge('e3', 'rag-1', 'end-1'),
      ];

      const result = validateWorkflow(nodes, edges);
      expect(result.valid).toBe(true);
      expect(result.warnings.some(w => w.includes('orphan'))).toBe(false);
    });
  });

  describe('Cycle detection', () => {
    it('detects simple cycle', () => {
      const nodes = [
        createNode('start-1', 'start'),
        createNode('llm-1', 'llm'),
        createNode('rag-1', 'rag'),
        createNode('end-1', 'end'),
      ];
      const edges = [
        createEdge('e1', 'start-1', 'llm-1'),
        createEdge('e2', 'llm-1', 'rag-1'),
        createEdge('e3', 'rag-1', 'llm-1'), // cycle: llm-1 -> rag-1 -> llm-1
        createEdge('e4', 'rag-1', 'end-1'),
      ];

      const result = validateWorkflow(nodes, edges);
      expect(result.valid).toBe(false);
      expect(result.errors.some(e => e.includes('Cycle detected'))).toBe(true);
    });

    it('detects self-loop', () => {
      const nodes = [
        createNode('start-1', 'start'),
        createNode('llm-1', 'llm'),
        createNode('end-1', 'end'),
      ];
      const edges = [
        createEdge('e1', 'start-1', 'llm-1'),
        createEdge('e2', 'llm-1', 'llm-1'), // self-loop
        createEdge('e3', 'llm-1', 'end-1'),
      ];

      const result = validateWorkflow(nodes, edges);
      expect(result.valid).toBe(false);
      expect(result.errors.some(e => e.includes('Cycle detected'))).toBe(true);
    });

    it('detects complex cycle', () => {
      const nodes = [
        createNode('start-1', 'start'),
        createNode('a', 'llm'),
        createNode('b', 'rag'),
        createNode('c', 'condition'),
        createNode('end-1', 'end'),
      ];
      const edges = [
        createEdge('e1', 'start-1', 'a'),
        createEdge('e2', 'a', 'b'),
        createEdge('e3', 'b', 'c'),
        createEdge('e4', 'c', 'a'), // cycle: a -> b -> c -> a
        createEdge('e5', 'c', 'end-1'),
      ];

      const result = validateWorkflow(nodes, edges);
      expect(result.valid).toBe(false);
      expect(result.errors.some(e => e.includes('Cycle detected'))).toBe(true);
    });

    it('passes for DAG (no cycles)', () => {
      const nodes = [
        createNode('start-1', 'start'),
        createNode('a', 'llm'),
        createNode('b', 'rag'),
        createNode('c', 'condition'),
        createNode('d', 'transform'),
        createNode('end-1', 'end'),
      ];
      const edges = [
        createEdge('e1', 'start-1', 'a'),
        createEdge('e2', 'a', 'b'),
        createEdge('e3', 'b', 'c'),
        createEdge('e4', 'c', 'd'),
        createEdge('e5', 'd', 'end-1'),
      ];

      const result = validateWorkflow(nodes, edges);
      expect(result.valid).toBe(true);
      expect(result.errors).toHaveLength(0);
    });
  });

  describe('Edge cases', () => {
    it('handles disconnected subgraphs', () => {
      const nodes = [
        createNode('start-1', 'start'),
        createNode('llm-1', 'llm'),
        createNode('end-1', 'end'),
        createNode('start-2', 'start'),
        createNode('llm-2', 'llm'),
        createNode('end-2', 'end'),
      ];
      const edges = [
        createEdge('e1', 'start-1', 'llm-1'),
        createEdge('e2', 'llm-1', 'end-1'),
        createEdge('e3', 'start-2', 'llm-2'),
        createEdge('e4', 'llm-2', 'end-2'),
      ];

      const result = validateWorkflow(nodes, edges);
      expect(result.valid).toBe(true); // valid but warns about multiple start nodes
      expect(result.warnings).toContain('Multiple start nodes found, only first will be used');
    });

    it('handles nodes with no edges at all', () => {
      const nodes = [
        createNode('start-1', 'start'),
        createNode('llm-1', 'llm'),
        createNode('end-1', 'end'),
      ];
      const edges: any[] = [];

      const result = validateWorkflow(nodes, edges);
      expect(result.valid).toBe(false); // orphan nodes
      expect(result.warnings.some(w => w.includes('orphan'))).toBe(true);
    });
  });
});