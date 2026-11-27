"""网关 → workflow-service 转发（试点）。

与 document-service 同一套思路：网关先验证 JWT，再用 `internal_headers()` 签名并注入
`X-Tenant-Id` / `X-User-Id`；响应包回网关的 `{success, data}` 信封。

两边的工作流「图」结构不同，必须转换（见 `proxy_adapters.py`）：
    网关节点 {id, type 大写, name, position, config, inputs[{id,...}]}
    微服务节点 {id, type 小写, position, config, inputs[str]}
    网关边 {source_node_id, target_node_id} → 微服务 {source, target}

只在 `GATEWAY_PROXY_WORKFLOWS=true` 时注册，默认关闭（网关 SQLite 与微服务 SQLite 不互通）。
明确不支持（返回 501）：`/workflows/{id}/unpublish`（微服务没有该接口）。
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from app.api.v1 import proxy_adapters as adapt
from app.api.v1.proxy import (
    _gateway_json,
    _json_body,
    _require_permission,
    _send,
    _upstream_error,
)
from app.core.config import settings
from app.core.security import get_current_user
from app.models import User, NotificationType
from app.services.notify import notify

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Gateway Proxy"])

_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]
_DEFAULT_PAGE_SIZE = 20


def _json(payload, status_code: int = 200):
    return _gateway_json(payload, status_code, proxy_name="workflow-service")


def _error(upstream):
    return _upstream_error(upstream, proxy_name="workflow-service")



async def _call(
    request: Request,
    user: User,
    *,
    method: str,
    path: str,
    query: list | None = None,
    payload: dict | None = None,
):
    body = (
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if payload is not None
        else None
    )
    return await _send(
        request,
        user,
        method=method,
        path=path,
        query=query,
        body=body,
        headers={"content-type": "application/json"},
        base_url=settings.WORKFLOW_SERVICE_URL,
    )


async def _body(request: Request) -> dict:
    try:
        payload = json.loads(await request.body() or b"{}")
    except (ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=422, detail="请求体必须是 JSON 对象")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="请求体必须是 JSON 对象")
    return payload


async def _list_workflows(request: Request, user: User) -> Response:
    params = request.query_params
    try:
        page = max(1, int(params.get("page") or 1))
        page_size = max(1, int(params.get("page_size") or _DEFAULT_PAGE_SIZE))
    except ValueError:
        raise HTTPException(status_code=422, detail="page / page_size 必须是整数")

    query: list[tuple[str, str]] = [
        ("skip", str((page - 1) * page_size)),
        ("limit", str(page_size)),
    ]
    if params.get("status"):
        query.append(("status_filter", str(params["status"]).lower()))

    upstream = await _call(
        request, user, method="GET", path="/api/v1/workflows", query=query
    )
    if upstream.status_code >= 400:
        return _error(upstream)

    workflows = _json_body(upstream)
    if not isinstance(workflows, list):
        raise HTTPException(status_code=502, detail="workflow-service 列表格式异常")
    try:
        total = int(upstream.headers.get("x-total-count", len(workflows)))
    except ValueError:
        total = len(workflows)

    items = [adapt.to_gateway_workflow_item(wf) for wf in workflows]
    return _json(adapt.envelope(adapt.paginated(items, total, page, page_size)))


async def _create_workflow(request: Request, user: User) -> Response:
    upstream = await _call(
        request,
        user,
        method="POST",
        path="/api/v1/workflows",
        payload=adapt.workflow_create_payload_to_ms(await _body(request)),
    )
    if upstream.status_code >= 400:
        return _error(upstream)
    return _json(
        adapt.envelope(adapt.to_gateway_workflow(_json_body(upstream))),
        status_code=upstream.status_code,
    )


async def _validate(request: Request, user: User) -> Response:
    body = await _body(request)
    definition = body.get("definition") or body
    # 微服务的 /workflows/validate 直接接收 definition（不是 {"definition": ...}）
    upstream = await _call(
        request,
        user,
        method="POST",
        path="/api/v1/workflows/validate",
        payload=adapt.workflow_definition_to_ms(definition),
    )
    if upstream.status_code >= 400:
        return _error(upstream)
    return _json(adapt.envelope(_json_body(upstream)))


async def _get_workflow(request: Request, user: User, wf_id: str) -> Response:
    method = request.method.upper()
    if method in ("PATCH", "PUT"):
        payload = adapt.workflow_update_payload_to_ms(await _body(request))
    else:
        payload = None

    upstream = await _call(
        request, user, method=method, path=f"/api/v1/workflows/{wf_id}", payload=payload
    )
    if upstream.status_code >= 400:
        return _error(upstream)
    if method == "DELETE":
        return _json(adapt.envelope(None))
    return _json(adapt.envelope(adapt.to_gateway_workflow(_json_body(upstream))))


async def _publish(request: Request, user: User, wf_id: str) -> Response:
    try:
        payload = await _body(request)
    except HTTPException:
        payload = {}
    upstream = await _call(
        request,
        user,
        method="POST",
        path=f"/api/v1/workflows/{wf_id}/publish",
        payload=payload,
    )
    if upstream.status_code >= 400:
        return _error(upstream)
    return _json(adapt.envelope(adapt.to_gateway_workflow(_json_body(upstream))))


async def _execute(request: Request, user: User, wf_id: str) -> Response:
    body = await _body(request)
    input_data = body.get("input_data") or body.get("input") or {}
    upstream = await _call(
        request,
        user,
        method="POST",
        path=f"/api/v1/workflows/{wf_id}/execute",
        payload={"input_data": input_data, "async_mode": bool(body.get("async_mode"))},
    )
    if upstream.status_code >= 400:
        return _error(upstream)
    result = _json_body(upstream)
    await _notify_execution(user, wf_id, result)
    return _json(
        adapt.envelope(
            adapt.to_gateway_execution(
                result, workflow_id=wf_id, tenant_id=str(user.tenant_id)
            )
        )
    )


async def _notify_execution(user: User, wf_id: str, result: dict) -> None:
    """执行真正结束时写一条通知（默认模式网关没有执行器，这条只在转发模式生效）。"""
    status_value = str(result.get("status") or "").lower()
    if status_value not in {"completed", "failed", "cancelled"}:
        return

    failed = status_value == "failed"
    execution_id = result.get("execution_id") or result.get("id") or "-"
    await notify(
        tenant_id=user.tenant_id,
        user_id=user.id,
        type=NotificationType.ERROR if failed else NotificationType.SUCCESS,
        title="工作流执行失败" if failed else "工作流执行完成",
        content=(
            result.get("error_message")
            or f"执行记录 {execution_id} 状态：{status_value}"
        ),
        data={
            "workflow_id": wf_id,
            "execution_id": str(execution_id),
            "status": status_value,
            "event": "workflow.execution.finished",
        },
    )


async def _executions(request: Request, user: User, wf_id: str) -> Response:
    params = request.query_params
    try:
        page = max(1, int(params.get("page") or 1))
        page_size = max(1, int(params.get("page_size") or _DEFAULT_PAGE_SIZE))
    except ValueError:
        raise HTTPException(status_code=422, detail="page / page_size 必须是整数")

    upstream = await _call(
        request,
        user,
        method="GET",
        path="/api/v1/executions",
        query=[
            ("workflow_id", wf_id),
            ("skip", str((page - 1) * page_size)),
            ("limit", str(page_size)),
        ],
    )
    if upstream.status_code >= 400:
        return _error(upstream)

    executions = _json_body(upstream)
    if not isinstance(executions, list):
        raise HTTPException(status_code=502, detail="workflow-service 执行记录格式异常")
    try:
        total = int(upstream.headers.get("x-total-count", len(executions)))
    except ValueError:
        total = len(executions)

    items = [adapt.to_gateway_execution_record(item) for item in executions]
    return _json(adapt.envelope(adapt.paginated(items, total, page, page_size)))


def _workflow_permission(method: str, path: str) -> str | None:
    """与 app/api/v1/workflows.py 的权限检查保持一致（validate 原本就不限权限）。"""
    if path == "/api/v1/workflows/validate":
        return None
    if path.endswith("/execute"):
        return "workflow:execute"
    if path.endswith("/publish"):
        return "workflow:update"
    if method == "GET":
        return "workflow:read"
    if method == "DELETE":
        return "workflow:delete"
    if method in ("PATCH", "PUT"):
        return "workflow:update"
    return "workflow:create"


async def _dispatch(request: Request, user: User) -> Response:
    path = request.url.path.rstrip("/") or "/api/v1/workflows"
    method = request.method.upper()
    permission = _workflow_permission(method, path)
    if permission:
        _require_permission(user, permission)

    if path == "/api/v1/workflows" and method == "GET":
        return await _list_workflows(request, user)
    if path == "/api/v1/workflows" and method == "POST":
        return await _create_workflow(request, user)
    if path == "/api/v1/workflows/validate" and method == "POST":
        return await _validate(request, user)

    if path.startswith("/api/v1/workflows/"):
        rest = path[len("/api/v1/workflows/") :]
        wf_id, _, suffix = rest.partition("/")
        if not suffix and method in ("GET", "PATCH", "PUT", "DELETE"):
            return await _get_workflow(request, user, wf_id)
        if suffix == "publish" and method == "POST":
            return await _publish(request, user, wf_id)
        if suffix == "execute" and method == "POST":
            return await _execute(request, user, wf_id)
        if suffix == "executions" and method == "GET":
            return await _executions(request, user, wf_id)
        if suffix == "unpublish" and method == "POST":
            return _json(
                adapt.error_envelope(
                    "workflow-service 没有 unpublish 接口；请改用 PATCH /workflows/{id} 把 status 设为 archived。",
                    code="NOT_IMPLEMENTED",
                ),
                status_code=501,
            )

    return _json(
        adapt.error_envelope(
            f"转发模式暂不支持该工作流接口：{method} {path}", code="NOT_IMPLEMENTED"
        ),
        status_code=501,
    )


@router.api_route("/workflows", methods=_METHODS, include_in_schema=False)
@router.api_route("/workflows/{path:path}", methods=_METHODS, include_in_schema=False)
async def proxy_workflows(request: Request, user: User = Depends(get_current_user)):
    return await _dispatch(request, user)
