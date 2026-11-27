import type { Edge, Node } from 'reactflow';

export interface ValidationResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
}

/**
 * 前端本地工作流校验：在调用后端 `/workflows/validate` 之前先挡住明显错误，
 * 断网或后端不可用时也能给出提示。后端仍然会做权威校验。
 *
 * 规则（与 tests/unit/workflow-validation.test.ts 对齐）：
 * - 至少一个节点、必须有一个 start 节点（多个 start 只告警）
 * - 没有 end 节点只告警（可能不终止）
 * - 除 start/end 外的孤立节点告警
 * - 一条边都没有但节点多于一个 → 错误（工作流根本连不起来）
 * - 有环 → 错误
 */
export function validateWorkflow(nodes: Node[], edges: Edge[]): ValidationResult {
  const errors: string[] = [];
  const warnings: string[] = [];

  if (!nodes || nodes.length === 0) {
    errors.push('Workflow must have at least one node');
    return { valid: false, errors, warnings };
  }

  const startNodes = nodes.filter((n) => n.data?.type === 'start');
  if (startNodes.length === 0) {
    errors.push('Workflow must have a start node');
  } else if (startNodes.length > 1) {
    warnings.push('Multiple start nodes found, only first will be used');
  }

  const endNodes = nodes.filter((n) => n.data?.type === 'end');
  if (endNodes.length === 0) {
    warnings.push('No end node found, workflow may not terminate properly');
  }

  const connectedNodes = new Set<string>();
  (edges || []).forEach((edge) => {
    connectedNodes.add(edge.source);
    connectedNodes.add(edge.target);
  });

  const orphanNodes = nodes.filter(
    (n) => n.data?.type !== 'start' && n.data?.type !== 'end' && !connectedNodes.has(n.id)
  );
  if (orphanNodes.length > 0) {
    warnings.push(`${orphanNodes.length} orphan nodes not connected to any edge`);
  }

  if ((edges || []).length === 0 && nodes.length > 1) {
    errors.push('Workflow has no edges: nodes are not connected to each other');
  }

  // 环检测（DFS + 递归栈）
  const adjacency = new Map<string, string[]>(nodes.map((n) => [n.id, []]));
  (edges || []).forEach((edge) => {
    if (adjacency.has(edge.source) && adjacency.has(edge.target)) {
      adjacency.get(edge.source)!.push(edge.target);
    }
  });

  const visited = new Set<string>();
  const inStack = new Set<string>();
  const cycles: string[][] = [];

  const dfs = (nodeId: string, path: string[]) => {
    visited.add(nodeId);
    inStack.add(nodeId);
    path.push(nodeId);

    for (const neighbor of adjacency.get(nodeId) || []) {
      if (!visited.has(neighbor)) {
        dfs(neighbor, [...path]);
      } else if (inStack.has(neighbor)) {
        const start = path.indexOf(neighbor);
        cycles.push([...path.slice(start), neighbor]);
      }
    }

    inStack.delete(nodeId);
  };

  nodes.forEach((n) => {
    if (!visited.has(n.id)) dfs(n.id, []);
  });

  cycles.forEach((cycle) => {
    errors.push(`Cycle detected: ${cycle.join(' -> ')}`);
  });

  return { valid: errors.length === 0, errors, warnings };
}
