"""默认单体模式下的最小工作流执行器。

真正的执行引擎在 `services/workflow-service/app/services/execution_engine.py`（LLM / 知识检索 /
条件分支都有），但默认模式不连它 —— 以前 `POST /workflows/{id}/execute` 只插一条 PENDING 记录就返回，
用户点「执行」永远没有结果。这里补一个诚实的、范围明确的最小执行器：

* 支持：START / END / HTTP / DELAY / LLM / RAG（线性执行，单出口）
  - LLM：走 `app/services/llm.py`（Ollama `/api/chat`），并把 token 用量记进 `cost_records`
  - RAG：走 `app/services/retrieval.py`（本地关键词检索），结果拼成 `{{rag_context}}` 供后续 LLM 节点用
* 不支持：CONDITION / TRANSFORM / PARALLEL / MERGE —— 预检阶段直接失败并说明原因，
  不会假装成功，也不会跑到一半留个半成品。

执行结果写进 `workflow_executions.output` / `node_executions`（节点级明细）/ `error`，
调用方（`api/v1/workflows.py`）负责落库并发通知。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CostRecord, ModelProvider
from app.services.llm import LLMError, LLMResult
from app.services.llm import chat as llm_chat
from app.services.retrieval import build_rag_context, retrieve_chunks

logger = logging.getLogger(__name__)

SUPPORTED_TYPES = {"START", "END", "HTTP", "DELAY", "LLM", "RAG"}
MAX_HTTP_TIMEOUT = 15.0
MAX_DELAY_MS = 10_000
MAX_BODY_CHARS = 2000


class WorkflowRunError(Exception):
    """可预期的执行失败：图不合法、节点类型不支持、HTTP 失败等。"""


@dataclass
class RunContext:
    """执行上下文：RAG 节点要查库，LLM 节点要落成本记录。"""

    db: Optional[AsyncSession] = None
    tenant_id: Optional[UUID] = None
    user_id: Optional[UUID] = None


@dataclass
class RunResult:
    status: str  # "completed" | "failed"
    output: Optional[dict]
    error: Optional[str]
    nodes: list[dict] = field(default_factory=list)
    duration_ms: int = 0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _render(value: Any, variables: dict) -> Any:
    """把 `{{name}}` 替换成变量值；只做字符串替换，行为可预测。"""
    if isinstance(value, str):
        for key, var in variables.items():
            value = value.replace("{{" + key + "}}", str(var))
        return value
    if isinstance(value, dict):
        return {k: _render(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [_render(v, variables) for v in value]
    return value


async def _record_llm_cost(ctx: RunContext, node: dict, result: LLMResult) -> None:
    """把这次模型调用记进成本表（本地模型没有单价，金额记 0，token 是真实的）。"""
    if ctx.db is None or ctx.tenant_id is None:
        return
    try:
        ctx.db.add(
            CostRecord(
                tenant_id=ctx.tenant_id,
                user_id=ctx.user_id,
                model_id=result.model,
                model_provider=ModelProvider.OLLAMA,
                operation_type="workflow_llm",
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                total_tokens=result.total_tokens,
                estimated_cost=Decimal("0"),
                currency="USD",
                meta={
                    "source": "workflow",
                    "node_id": str(node.get("id")),
                    "node_name": node.get("name"),
                },
            )
        )
        await ctx.db.flush()
    except Exception:
        logger.warning("记录工作流模型成本失败（不影响执行）", exc_info=True)


async def _run_node(node: dict, variables: dict, input_data: dict, ctx: RunContext) -> dict:
    node_type = str(node.get("type") or "").upper()
    config = node.get("config") or {}

    if node_type == "START":
        return {"input": dict(input_data or {})}

    if node_type == "END":
        return {"output": dict(variables)}

    if node_type == "DELAY":
        try:
            requested = int(config.get("duration_ms") or 0)
        except (TypeError, ValueError):
            raise WorkflowRunError("延时节点的 duration_ms 必须是整数")
        ms = max(0, min(requested, MAX_DELAY_MS))
        await asyncio.sleep(ms / 1000)
        return {"slept_ms": ms}

    if node_type == "HTTP":
        url = str(_render(config.get("url") or "", variables)).strip()
        if not url:
            raise WorkflowRunError("HTTP 节点缺少 url")
        method = str(config.get("method") or "GET").upper()
        headers = _render(config.get("headers") or {}, variables)
        body = _render(config.get("body") or {}, variables)
        payload = body if method in {"POST", "PUT", "PATCH"} and body else None
        try:
            async with httpx.AsyncClient(timeout=MAX_HTTP_TIMEOUT, follow_redirects=True) as client:
                resp = await client.request(method, url, headers=headers, json=payload)
        except httpx.RequestError as exc:
            raise WorkflowRunError(f"请求 {url} 失败：{exc}")

        text = resp.text[:MAX_BODY_CHARS]
        try:
            parsed = resp.json()
        except ValueError:
            parsed = None
        if resp.status_code >= 400:
            raise WorkflowRunError(f"HTTP {resp.status_code}：{text[:200]}")

        # 把响应里的对象字段并进变量，后面的节点可以用 {{field}} 引用
        if isinstance(parsed, dict):
            variables.update(parsed)
        return {"status_code": resp.status_code, "body": parsed if parsed is not None else text}

    if node_type == "LLM":
        prompt_template = str(config.get("prompt_template") or "").strip()
        if not prompt_template:
            raise WorkflowRunError("LLM 节点缺少 prompt_template")
        prompt = str(_render(prompt_template, variables))
        try:
            result = await llm_chat(
                [{"role": "user", "content": prompt}],
                model=config.get("model") or None,
                temperature=float(config.get("temperature") or 0.7),
                max_tokens=int(config.get("max_tokens") or 2048),
            )
        except LLMError as exc:
            raise WorkflowRunError(
                f"调用模型失败：{exc}（检查 OLLAMA_BASE_URL / OLLAMA_CHAT_MODEL 是否正确）"
            )
        except (TypeError, ValueError) as exc:
            raise WorkflowRunError(f"LLM 节点参数不合法：{exc}")

        if not result.content.strip():
            raise WorkflowRunError("模型返回了空内容")
        variables["llm_output"] = result.content
        variables["llm_model"] = result.model
        await _record_llm_cost(ctx, node, result)
        return {
            "content": result.content,
            "model": result.model,
            "prompt_tokens": result.prompt_tokens,
            "completion_tokens": result.completion_tokens,
        }

    if node_type == "RAG":
        kb_raw = str(config.get("knowledge_base_id") or "").strip()
        if not kb_raw:
            raise WorkflowRunError("RAG 节点缺少 knowledge_base_id")
        try:
            kb_id = UUID(kb_raw)
        except ValueError:
            raise WorkflowRunError(f"knowledge_base_id 不是合法 UUID：{kb_raw}")

        query = str(_render(config.get("query_template") or "", variables)).strip()
        if not query:
            query = str(variables.get("message") or "").strip()
        if not query:
            raise WorkflowRunError("RAG 节点没有查询语句（query_template 渲染后为空）")
        if ctx.db is None:
            raise WorkflowRunError("RAG 节点需要数据库会话，当前执行上下文里没有")

        try:
            top_k = max(1, min(int(config.get("top_k") or 5), 20))
        except (TypeError, ValueError):
            top_k = 5

        chunks = await retrieve_chunks(ctx.db, kb_id, query, top_k=top_k)
        variables["rag_context"] = build_rag_context(chunks)
        variables["chunk_count"] = len(chunks)
        return {
            "count": len(chunks),
            "query": query,
            "chunks": [
                {
                    "chunk_id": c["chunk_id"],
                    "document_id": c["document_id"],
                    "document_filename": c["document_filename"],
                    "score": c["score"],
                    "content": c["content"][:200],
                }
                for c in chunks
            ],
        }

    raise WorkflowRunError(f"不支持的节点类型：{node_type}")


def _node_run(node: dict, status: str, *, output=None, error=None, started_at=None, completed_at=None) -> dict:
    started = started_at or _now()
    completed = completed_at or _now()
    # 时间统一存 ISO 字符串：JSONB 列不会给 datetime 做序列化，写库时会直接 TypeError
    return {
        "node_id": str(node.get("id")),
        "status": status,
        "input": None,
        "output": output,
        "error": error,
        "started_at": started.isoformat(),
        "completed_at": completed.isoformat(),
        "duration_ms": max(0, int((completed - started).total_seconds() * 1000)),
    }


async def run_workflow(
    definition: Optional[dict],
    input_data: Optional[dict],
    ctx: Optional[RunContext] = None,
) -> RunResult:
    """按 DAG 线性执行工作流；节点级错误以 status="failed" 返回，图级错误直接抛 WorkflowRunError。"""
    definition = definition or {}
    nodes = {n.get("id"): n for n in (definition.get("nodes") or []) if isinstance(n, dict) and n.get("id")}
    edges = [e for e in (definition.get("edges") or []) if isinstance(e, dict)]
    if not nodes:
        raise WorkflowRunError("工作流没有节点，无法执行")

    types = {str(n.get("type") or "").upper() for n in nodes.values()}
    unsupported = sorted(types - SUPPORTED_TYPES)
    if unsupported:
        raise WorkflowRunError(
            "默认执行器暂不支持这些节点类型："
            + "、".join(unsupported)
            + "（目前支持 START / END / HTTP / DELAY / LLM / RAG；条件分支、并行、合并要用 workflow-service）"
        )

    starts = [n for n in nodes.values() if str(n.get("type") or "").upper() == "START"]
    if not starts:
        raise WorkflowRunError("工作流没有 START 节点，执行器不知道从哪里开始")
    if len(starts) > 1:
        raise WorkflowRunError("工作流有多个 START 节点，执行器无法确定入口")

    outgoing: dict[str, list[str]] = {}
    for edge in edges:
        source = edge.get("source_node_id")
        target = edge.get("target_node_id")
        if source in nodes and target in nodes:
            outgoing.setdefault(source, []).append(target)

    variables = dict(input_data or {})
    input_snapshot = dict(input_data or {})
    runs: list[dict] = []
    started_all = _now()
    current: Optional[dict] = starts[0]
    visited: set[str] = set()
    last_output: Optional[dict] = None

    while current is not None:
        node_id = str(current.get("id"))
        if node_id in visited:
            return RunResult(
                status="failed",
                output=None,
                error=f"工作流存在环：节点 {node_id} 会被重复执行，执行器已中止",
                nodes=runs,
                duration_ms=int((_now() - started_all).total_seconds() * 1000),
            )
        visited.add(node_id)

        node_type = str(current.get("type") or "").upper()
        node_started = _now()
        try:
            output = await _run_node(current, variables, input_snapshot, ctx or RunContext())
        except WorkflowRunError as exc:
            runs.append(
                _node_run(current, "failed", error=str(exc), started_at=node_started, completed_at=_now())
            )
            name = current.get("name") or node_id
            return RunResult(
                status="failed",
                output=None,
                error=f"节点「{name}」执行失败：{exc}",
                nodes=runs,
                duration_ms=int((_now() - started_all).total_seconds() * 1000),
            )

        runs.append(_node_run(current, "completed", output=output, started_at=node_started, completed_at=_now()))
        last_output = output

        if node_type == "END":
            break

        targets = outgoing.get(node_id, [])
        if len(targets) > 1:
            return RunResult(
                status="failed",
                output=None,
                error=f"节点「{current.get('name') or node_id}」有 {len(targets)} 条出边：默认执行器不支持分支，请改用条件分支 + workflow-service",
                nodes=runs,
                duration_ms=int((_now() - started_all).total_seconds() * 1000),
            )
        current = nodes.get(targets[0]) if targets else None

    return RunResult(
        status="completed",
        output=last_output if last_output is not None else {"output": variables},
        error=None,
        nodes=runs,
        duration_ms=int((_now() - started_all).total_seconds() * 1000),
    )
