import asyncio
import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

import httpx

from app.core.config import settings
from app.core.logging import setup_logging
from app.models import (
    Workflow,
    WorkflowExecution,
    WorkflowExecutionLog,
    ExecutionStatus,
    NodeType,
    LogLevel,
)
from app.db.session import session_context
from app.core.context import current_tenant_id

setup_logging()
import structlog
logger = structlog.get_logger()


class NodeExecutor(ABC):
    """Base class for node executors."""

    @abstractmethod
    async def execute(
        self,
        node_id: str,
        config: Dict[str, Any],
        inputs: Dict[str, Any],
        context: "ExecutionContext",
    ) -> Dict[str, Any]:
        pass

    @abstractmethod
    def validate_config(self, config: Dict[str, Any]) -> bool:
        pass


@dataclass
class ExecutionContext:
    execution_id: str
    workflow_id: str
    tenant_id: str
    input_data: Dict[str, Any]
    node_outputs: Dict[str, Any] = field(default_factory=dict)
    variables: Dict[str, Any] = field(default_factory=dict)
    http_client: httpx.AsyncClient = None

    def __post_init__(self):
        if self.http_client is None:
            self.http_client = httpx.AsyncClient(timeout=settings.EXECUTION_TIMEOUT_SECONDS)

    async def close(self):
        if self.http_client:
            await self.http_client.aclose()


class StartNodeExecutor(NodeExecutor):
    def validate_config(self, config: Dict[str, Any]) -> bool:
        return True

    async def execute(self, node_id: str, config: Dict[str, Any], inputs: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
        # Start node just passes through the workflow input
        return context.input_data


class EndNodeExecutor(NodeExecutor):
    def validate_config(self, config: Dict[str, Any]) -> bool:
        return True

    async def execute(self, node_id: str, config: Dict[str, Any], inputs: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
        # End node returns the final output
        return inputs.get("input", {})


class LLMNodeExecutor(NodeExecutor):
    def validate_config(self, config: Dict[str, Any]) -> bool:
        required = ["model", "prompt_template"]
        return all(k in config for k in required)

    async def execute(self, node_id: str, config: Dict[str, Any], inputs: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
        # Render prompt template with inputs
        prompt = self._render_template(config["prompt_template"], inputs)

        # Call LLM service
        async with httpx.AsyncClient(timeout=settings.EXECUTION_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{settings.LLM_SERVICE_URL}/api/v1/chat/completions",
                json={
                    "model": config["model"],
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": config.get("temperature", 0.7),
                    "max_tokens": config.get("max_tokens", 4096),
                    "stream": False,
                },
            )
            response.raise_for_status()
            result = response.json()

        return {
            "response": result["choices"][0]["message"]["content"],
            "usage": result.get("usage", {}),
            "model": config["model"],
        }

    def _render_template(self, template: str, inputs: Dict[str, Any]) -> str:
        # Simple template rendering - replace {{variable}} with values
        import re
        def replace_var(match):
            var_name = match.group(1).strip()
            # Support nested access like inputs.user_question
            parts = var_name.split(".")
            value = inputs
            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part, "")
                else:
                    value = getattr(value, part, "")
            return str(value) if value is not None else ""

        return re.sub(r"\{\{(\w+(?:\.\w+)*)\}\}", replace_var, template)


class RAGNodeExecutor(NodeExecutor):
    def validate_config(self, config: Dict[str, Any]) -> bool:
        required = ["knowledge_base_id", "query_template"]
        return all(k in config for k in required)

    async def execute(self, node_id: str, config: Dict[str, Any], inputs: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
        # Render query template
        query = self._render_template(config["query_template"], inputs)

        # Call RAG service
        async with httpx.AsyncClient(timeout=settings.EXECUTION_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{settings.RAG_SERVICE_URL}/api/v1/retrieval/search",
                json={
                    "query": query,
                    "knowledge_base_id": config["knowledge_base_id"],
                    "top_k": config.get("top_k", 5),
                    "use_rerank": config.get("use_rerank", True),
                },
            )
            response.raise_for_status()
            result = response.json()

        # Format chunks for output
        chunks = result.get("chunks", [])
        context_text = "\n\n".join([f"[来源: {c['document_filename']}]\n{c['content']}" for c in chunks])

        return {
            "chunks": chunks,
            "context": context_text,
            "query": query,
            "total_found": result.get("total_found", 0),
        }

    def _render_template(self, template: str, inputs: Dict[str, Any]) -> str:
        import re
        def replace_var(match):
            var_name = match.group(1).strip()
            parts = var_name.split(".")
            value = inputs
            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part, "")
                else:
                    value = getattr(value, part, "")
            return str(value) if value is not None else ""
        return re.sub(r"\{\{(\w+(?:\.\w+)*)\}\}", replace_var, template)


class ConditionNodeExecutor(NodeExecutor):
    def validate_config(self, config: Dict[str, Any]) -> bool:
        return "condition" in config

    async def execute(self, node_id: str, config: Dict[str, Any], inputs: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
        # Evaluate condition expression
        condition = config["condition"]
        try:
            # Simple expression evaluation - in production use a proper expression evaluator
            result = eval(condition, {"__builtins__": {}}, inputs)
            return {"result": bool(result), "branch": "true" if result else "false"}
        except Exception as e:
            logger.error("Condition evaluation failed", error=str(e), condition=condition)
            return {"result": False, "branch": "false", "error": str(e)}


class TransformNodeExecutor(NodeExecutor):
    def validate_config(self, config: Dict[str, Any]) -> bool:
        return "transform" in config

    async def execute(self, node_id: str, config: Dict[str, Any], inputs: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
        # Apply transformation (JQ-like or Python expression)
        transform = config["transform"]
        try:
            # Support simple key mapping
            if isinstance(transform, dict):
                result = {}
                for key, expr in transform.items():
                    result[key] = eval(expr, {"__builtins__": {}}, inputs)
                return result
            else:
                return {"result": eval(transform, {"__builtins__": {}}, inputs)}
        except Exception as e:
            logger.error("Transform failed", error=str(e))
            return {"error": str(e)}


class HTTPNodeExecutor(NodeExecutor):
    def validate_config(self, config: Dict[str, Any]) -> bool:
        required = ["url", "method"]
        return all(k in config for k in required)

    async def execute(self, node_id: str, config: Dict[str, Any], inputs: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
        url = self._render_template(config["url"], inputs)
        method = config["method"].upper()
        headers = config.get("headers", {})
        body = config.get("body")

        if body and isinstance(body, dict):
            body = self._render_template_json(body, inputs)

        async with httpx.AsyncClient(timeout=config.get("timeout", 30)) as client:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                json=body if body else None,
            )

        return {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "body": response.json() if response.headers.get("content-type", "").startswith("application/json") else response.text,
        }

    def _render_template(self, template: str, inputs: Dict[str, Any]) -> str:
        import re
        def replace_var(match):
            var_name = match.group(1).strip()
            parts = var_name.split(".")
            value = inputs
            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part, "")
                else:
                    value = getattr(value, part, "")
            return str(value) if value is not None else ""
        return re.sub(r"\{\{(\w+(?:\.\w+)*)\}\}", replace_var, template)

    def _render_template_json(self, obj: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        result = {}
        for key, value in obj.items():
            if isinstance(value, str):
                result[key] = self._render_template(value, inputs)
            elif isinstance(value, dict):
                result[key] = self._render_template_json(value, inputs)
            elif isinstance(value, list):
                result[key] = [self._render_template_json(v, inputs) if isinstance(v, dict) else (self._render_template(v, inputs) if isinstance(v, str) else v) for v in value]
            else:
                result[key] = value
        return result


class DelayNodeExecutor(NodeExecutor):
    def validate_config(self, config: Dict[str, Any]) -> bool:
        return "duration_ms" in config

    async def execute(self, node_id: str, config: Dict[str, Any], inputs: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
        duration = config["duration_ms"] / 1000.0
        await asyncio.sleep(duration)
        return {"delayed": duration}


class ParallelNodeExecutor(NodeExecutor):
    def validate_config(self, config: Dict[str, Any]) -> bool:
        return "branches" in config

    async def execute(self, node_id: str, config: Dict[str, Any], inputs: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
        branches = config["branches"]
        # Execute all branches in parallel
        tasks = []
        for branch in branches:
            # Each branch is a sub-workflow or node sequence
            # For simplicity, we just pass inputs through
            tasks.append(self._execute_branch(branch, inputs, context))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        return {f"branch_{i}": r for i, r in enumerate(results)}

    async def _execute_branch(self, branch: Dict[str, Any], inputs: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
        # Simplified branch execution
        return {"status": "completed", "inputs": inputs}


class MergeNodeExecutor(NodeExecutor):
    def validate_config(self, config: Dict[str, Any]) -> bool:
        return "strategy" in config

    async def execute(self, node_id: str, config: Dict[str, Any], inputs: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
        strategy = config.get("strategy", "concat")  # concat, merge, first
        branch_outputs = inputs.get("branch_outputs", {})

        if strategy == "concat":
            return {"merged": list(branch_outputs.values())}
        elif strategy == "merge":
            result = {}
            for v in branch_outputs.values():
                if isinstance(v, dict):
                    result.update(v)
            return {"merged": result}
        elif strategy == "first":
            first_key = next(iter(branch_outputs))
            return {"merged": branch_outputs[first_key]}
        return {"merged": branch_outputs}


class NodeExecutorRegistry:
    _executors: Dict[NodeType, NodeExecutor] = {}

    @classmethod
    def register(cls, node_type: NodeType, executor: NodeExecutor):
        cls._executors[node_type] = executor

    @classmethod
    def get(cls, node_type: NodeType) -> Optional[NodeExecutor]:
        return cls._executors.get(node_type)

    @classmethod
    def initialize(cls):
        cls.register(NodeType.START, StartNodeExecutor())
        cls.register(NodeType.END, EndNodeExecutor())
        cls.register(NodeType.LLM, LLMNodeExecutor())
        cls.register(NodeType.RAG, RAGNodeExecutor())
        cls.register(NodeType.CONDITION, ConditionNodeExecutor())
        cls.register(NodeType.TRANSFORM, TransformNodeExecutor())
        cls.register(NodeType.HTTP, HTTPNodeExecutor())
        cls.register(NodeType.DELAY, DelayNodeExecutor())
        cls.register(NodeType.PARALLEL, ParallelNodeExecutor())
        cls.register(NodeType.MERGE, MergeNodeExecutor())


NodeExecutorRegistry.initialize()


class WorkflowExecutionEngine:
    """Main workflow execution engine."""

    def __init__(self):
        self.running_executions: Dict[str, asyncio.Task] = {}

    async def execute(
        self,
        execution_id: str,
        workflow: Workflow,
        input_data: Dict[str, Any],
        async_mode: bool = False,
    ) -> Dict[str, Any]:
        """Execute a workflow."""
        if async_mode:
            task = asyncio.create_task(self._execute_sync(execution_id, workflow, input_data))
            self.running_executions[execution_id] = task
            return {"execution_id": execution_id, "status": "started"}

        return await self._execute_sync(execution_id, workflow, input_data)

    async def _execute_sync(
        self,
        execution_id: str,
        workflow: Workflow,
        input_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        start_time = time.time()
        context = ExecutionContext(
            execution_id=execution_id,
            workflow_id=str(workflow.id),
            tenant_id=str(workflow.tenant_id),
            input_data=input_data,
        )

        try:
            # Update execution status to RUNNING
            await self._update_execution_status(execution_id, ExecutionStatus.RUNNING, started_at=datetime.utcnow())

            # Build execution graph
            definition = workflow.definition
            nodes = definition.get("nodes", [])
            edges = definition.get("edges", [])

            # Find start node
            start_nodes = [n for n in nodes if n["type"] == NodeType.START]
            if not start_nodes:
                raise ValueError("No start node found")

            # Topological sort for execution order
            execution_order = self._topological_sort(nodes, edges)

            # Execute nodes in order
            for node_def in execution_order:
                node_id = node_def["id"]
                NodeType(node_def["type"])  # 非法类型在这里就抛错，保留校验

                # Check if execution was cancelled
                exec_status = await self._get_execution_status(execution_id)
                if exec_status == ExecutionStatus.CANCELLED:
                    raise asyncio.CancelledError("Execution cancelled")

                # Update current node
                await self._update_current_node(execution_id, node_id)

                # Execute node
                await self._execute_node(node_def, context)

            # Execution completed successfully
            output_data = context.node_outputs.get("end", context.node_outputs)
            await self._update_execution_status(
                execution_id,
                ExecutionStatus.COMPLETED,
                output_data=output_data,
                completed_at=datetime.utcnow(),
            )

            duration_ms = int((time.time() - start_time) * 1000)
            return {"status": "completed", "output": output_data, "duration_ms": duration_ms}

        except asyncio.CancelledError:
            await self._update_execution_status(execution_id, ExecutionStatus.CANCELLED, completed_at=datetime.utcnow())
            raise
        except Exception as e:
            logger.error("Workflow execution failed", execution_id=execution_id, error=str(e))
            await self._update_execution_status(
                execution_id,
                ExecutionStatus.FAILED,
                error_message=str(e),
                completed_at=datetime.utcnow(),
            )
            return {"status": "failed", "error": str(e), "duration_ms": int((time.time() - start_time) * 1000)}
        finally:
            await context.close()

    def _topological_sort(self, nodes: List[Dict], edges: List[Dict]) -> List[Dict]:
        """Sort nodes in topological order based on edges."""
        # Build adjacency list and in-degree count
        node_map = {n["id"]: n for n in nodes}
        in_degree = {n["id"]: 0 for n in nodes}
        adj = {n["id"]: [] for n in nodes}

        for edge in edges:
            source = edge["source"]
            target = edge["target"]
            if source in adj and target in in_degree:
                adj[source].append(target)
                in_degree[target] += 1

        # Kahn's algorithm
        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        result = []

        while queue:
            nid = queue.pop(0)
            if nid in node_map:
                result.append(node_map[nid])
            for neighbor in adj.get(nid, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # Check for cycles
        if len(result) != len(nodes):
            logger.warning("Cycle detected in workflow graph, using original order")
            return nodes

        return result

    async def _execute_node(self, node_def: Dict, context: ExecutionContext):
        node_id = node_def["id"]
        node_type = NodeType(node_def["type"])
        config = node_def.get("config", {})

        # Get executor
        executor = NodeExecutorRegistry.get(node_type)
        if not executor:
            raise ValueError(f"No executor for node type: {node_type}")

        # Validate config
        if not executor.validate_config(config):
            raise ValueError(f"Invalid config for node {node_id}: {config}")

        # Gather inputs from connected edges
        node_inputs = self._gather_inputs(node_id, context)

        # Log start
        await self._log_execution(context.execution_id, node_id, node_type, LogLevel.INFO, f"Starting node {node_id}", node_inputs)

        node_start = time.time()
        try:
            # Execute node
            output = await executor.execute(node_id, config, node_inputs, context)

            # Store output
            context.node_outputs[node_id] = output

            # Log success
            duration_ms = int((time.time() - node_start) * 1000)
            await self._log_execution(
                context.execution_id, node_id, node_type, LogLevel.INFO,
                f"Node {node_id} completed", node_inputs, output, duration_ms
            )

        except Exception as e:
            duration_ms = int((time.time() - node_start) * 1000)
            await self._log_execution(
                context.execution_id, node_id, node_type, LogLevel.ERROR,
                f"Node {node_id} failed: {str(e)}", node_inputs, None, duration_ms, str(e)
            )
            raise

    def _gather_inputs(self, node_id: str, context: ExecutionContext) -> Dict[str, Any]:
        """Gather inputs from upstream nodes."""
        # In a full implementation, this would trace edges to find source nodes
        # For now, return all previous outputs
        return context.node_outputs

    async def _log_execution(
        self,
        execution_id: str,
        node_id: str,
        node_type: NodeType,
        level: LogLevel,
        message: str,
        input_data: Optional[Dict] = None,
        output_data: Optional[Dict] = None,
        duration_ms: int = 0,
        error_message: Optional[str] = None,
    ):
        async with session_context() as session:
            log = WorkflowExecutionLog(
                execution_id=uuid.UUID(execution_id),
                tenant_id=current_tenant_id(),
                node_id=node_id,
                node_type=node_type,
                level=level,
                message=message,
                input_data=input_data,
                output_data=output_data,
                error_message=error_message,
                duration_ms=duration_ms,
            )
            session.add(log)

    async def _update_execution_status(
        self,
        execution_id: str,
        status: ExecutionStatus,
        output_data: Optional[Dict] = None,
        error_message: Optional[str] = None,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
    ):
        async with session_context() as session:
            execution = await session.get(WorkflowExecution, uuid.UUID(execution_id))
            if execution:
                execution.status = status
                if output_data is not None:
                    execution.output_data = output_data
                if error_message is not None:
                    execution.error_message = error_message
                if started_at is not None:
                    execution.started_at = started_at
                if completed_at is not None:
                    execution.completed_at = completed_at

    async def _get_execution_status(self, execution_id: str) -> ExecutionStatus:
        async with session_context() as session:
            execution = await session.get(WorkflowExecution, uuid.UUID(execution_id))
            return execution.status if execution else ExecutionStatus.FAILED

    async def _update_current_node(self, execution_id: str, node_id: str):
        async with session_context() as session:
            execution = await session.get(WorkflowExecution, uuid.UUID(execution_id))
            if execution:
                execution.current_node_id = node_id

    async def cancel_execution(self, execution_id: str, reason: Optional[str] = None):
        """Cancel a running execution."""
        if execution_id in self.running_executions:
            task = self.running_executions[execution_id]
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            del self.running_executions[execution_id]

        await self._update_execution_status(
            execution_id,
            ExecutionStatus.CANCELLED,
            error_message=reason,
            completed_at=datetime.utcnow(),
        )


engine = WorkflowExecutionEngine()