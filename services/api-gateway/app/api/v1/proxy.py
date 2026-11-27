"""网关 → 微服务转发（试点：document-service）。

背景：网关一直是「单体」，`app/core/internal_auth.py#internal_headers()` 早就写好了，
却没有任何调用方。这个路由把 `/documents`、`/upload`、`/download` 三组路径转给
document-service，并**用网关解析出的 JWT 身份**签名后注入 `X-Tenant-Id` / `X-User-Id`，
微服务侧第 6 轮的签名中间件会验签。

对外契约保持不变：响应统一包成网关的 `{success, data}` 信封，字段名用网关的
`file_name` / `mime_type` / `type`（转换见 `proxy_adapters.py`），所以前端不需要改接口层。
真正对不上的只有两处，已明确降级：

- 文档分块列表 `/documents/{id}/chunks`：网关的分块查自己的库，document-service 没有这个接口 → 501。
- 列表的 `search` / `type` 过滤document-service 不支持 → 忽略（分页与 `status` 已透传）。

只在 `GATEWAY_PROXY_DOCUMENTS=true` 时注册（见 `app/main.py`）。默认关闭，因为网关 SQLite
与微服务 SQLite 是两套库，打开后演示数据不会自动迁移。
"""

from __future__ import annotations

import json
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from app.api.v1 import proxy_adapters as adapt
from app.core.config import settings
from app.core.internal_auth import internal_headers
from app.core.security import (
    get_current_user,
    get_role_permissions,
    has_permission,
)
from app.models import User, NotificationType
from app.services.notify import notify

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Gateway Proxy"])

# 逐跳头不能转发（RFC 7230）；Authorization 也不透传：微服务不认 JWT，只认内部签名。
_DROP_HEADERS = {
    "host",
    "content-length",
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "authorization",
}

_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]
_PROXY_HEADER = {"X-Gateway-Proxy": "document-service"}
_DEFAULT_PAGE_SIZE = 20


def _require_permission(user: User, permission: str) -> None:
    """转发不经过网关的 RBAC 依赖，这里按同样的权限表补上，否则任何登录用户都能删文档。"""
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    if not has_permission(get_role_permissions(role), permission):
        raise HTTPException(status_code=403, detail=f"权限不足：{permission}")


def _document_permission(method: str, path: str) -> str:
    """把请求方法/路径映射到网关的权限名（与 app/api/v1/documents.py 保持一致）。"""
    if method == "GET":
        return "document:read"
    if method == "DELETE":
        return "document:delete"
    if method in ("PATCH", "PUT"):
        return "document:update"
    if path.endswith("/reprocess"):
        return "document:update"
    return "document:create"


def _request_headers(request: Request) -> dict:
    return {
        name: value
        for name, value in request.headers.items()
        if name.lower() not in _DROP_HEADERS
    }


def _build_headers(
    request: Request,
    user: User,
    method: str,
    path: str,
    override: dict | None = None,
) -> dict:
    """转发头：剔除逐跳头/Authorization，再加内部签名与租户/用户身份。"""
    forward_headers = dict(override if override is not None else _request_headers(request))
    try:
        forward_headers.update(
            internal_headers(method, path, str(user.tenant_id), str(user.id))
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=f"网关未配置内部签名密钥：{exc}")
    return forward_headers


async def _send(
    request: Request,
    user: User,
    *,
    method: str,
    path: str,
    query: list | None = None,
    body: bytes | None = None,
    headers: dict | None = None,
    base_url: str | None = None,
) -> httpx.Response:
    """带上内部签名把请求发给微服务（小体积 JSON 用，全量缓冲）。"""
    base = base_url or settings.DOCUMENT_SERVICE_URL
    target = base.rstrip("/") + path
    forward_headers = _build_headers(request, user, method, path, headers)

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            return await client.request(
                method,
                target,
                params=query or None,
                content=body,
                headers=forward_headers,
            )
    except httpx.RequestError as exc:
        logger.warning("proxy to upstream failed: %s %s (%s)", method, target, exc)
        raise HTTPException(status_code=502, detail=f"上游服务不可达（{base}）：{exc}")


def _gateway_json(payload, status_code: int = 200, proxy_name: str = "document-service") -> JSONResponse:
    return JSONResponse(
        content=payload,
        status_code=status_code,
        headers={"X-Gateway-Proxy": proxy_name},
    )


def _upstream_error(upstream: httpx.Response, proxy_name: str = "document-service") -> JSONResponse:
    """把微服务的错误详情包成网关的错误信封，状态码保持一致。"""
    message = upstream.text[:500] or f"上游返回 {upstream.status_code}"
    try:
        parsed = upstream.json()
        if isinstance(parsed, dict) and parsed.get("detail"):
            message = str(parsed["detail"])
    except (ValueError, json.JSONDecodeError):
        pass
    return _gateway_json(
        adapt.error_envelope(message), status_code=upstream.status_code, proxy_name=proxy_name
    )


def _json_body(upstream: httpx.Response):
    try:
        return upstream.json()
    except (ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=502, detail="document-service 返回了非 JSON 内容")


def _pass_through_headers(upstream: httpx.Response) -> dict:
    headers = dict(_PROXY_HEADER)
    for name in ("content-type", "content-disposition", "content-language", "etag"):
        if upstream.headers.get(name):
            headers[name.title()] = upstream.headers[name]
    return headers


async def _forward_generic(request: Request, user: User, path: str | None = None) -> Response:
    """未适配的路径：流式转发（请求体与响应体都不整块缓冲）。

    文件上传/下载走这里：大文件不会在网关内存里再拷一份。
    """
    upstream_path = path or request.url.path
    target = settings.DOCUMENT_SERVICE_URL.rstrip("/") + upstream_path
    headers = _build_headers(request, user, request.method, upstream_path)

    client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, read=None))
    try:
        upstream_request = client.build_request(
            request.method,
            target,
            params=list(request.query_params.multi_items()),
            content=request.stream(),
            headers=headers,
        )
        upstream = await client.send(upstream_request, stream=True)
    except httpx.RequestError as exc:
        await client.aclose()
        logger.warning("proxy stream to document-service failed: %s (%s)", target, exc)
        raise HTTPException(
            status_code=502,
            detail=f"document-service 不可达（{settings.DOCUMENT_SERVICE_URL}）：{exc}",
        )

    content_type = upstream.headers.get("content-type", "")
    if upstream.status_code >= 400 and "application/json" in content_type:
        # 错误体很小，读完整再包成网关错误信封
        data = await upstream.aread()
        await upstream.aclose()
        await client.aclose()
        message = data.decode("utf-8", "replace")[:500] or f"上游返回 {upstream.status_code}"
        try:
            parsed = json.loads(data)
            if isinstance(parsed, dict) and parsed.get("detail"):
                message = str(parsed["detail"])
        except (ValueError, json.JSONDecodeError):
            pass
        return _gateway_json(adapt.error_envelope(message), status_code=upstream.status_code)

    if upstream.status_code < 400 and "application/json" in content_type:
        data = await upstream.aread()
        await upstream.aclose()
        await client.aclose()
        try:
            parsed = json.loads(data)
        except (ValueError, json.JSONDecodeError):
            raise HTTPException(status_code=502, detail="document-service 返回了非 JSON 内容")
        return _gateway_json(adapt.envelope(parsed), status_code=upstream.status_code)

    async def body_stream():
        try:
            async for chunk in upstream.aiter_bytes():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        body_stream(),
        status_code=upstream.status_code,
        headers=_pass_through_headers(upstream),
    )


# ============================================
# 文档接口（契约适配）
# ============================================


async def _list_documents(request: Request, user: User) -> Response:
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
    if params.get("knowledge_base_id"):
        query.append(("knowledge_base_id", params["knowledge_base_id"]))
    if params.get("status"):
        query.append(("status_filter", params["status"]))

    upstream = await _send(
        request, user, method="GET", path="/api/v1/documents", query=query
    )
    if upstream.status_code >= 400:
        return _upstream_error(upstream)

    docs = _json_body(upstream)
    if not isinstance(docs, list):
        raise HTTPException(status_code=502, detail="document-service 文档列表格式异常")
    try:
        total = int(upstream.headers.get("x-total-count", len(docs)))
    except ValueError:
        total = len(docs)

    items = [adapt.to_gateway_list_item(doc) for doc in docs]
    return _gateway_json(adapt.envelope(adapt.paginated(items, total, page, page_size)))


async def _create_document(request: Request, user: User) -> Response:
    try:
        body = json.loads(await request.body() or b"{}")
    except (ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=422, detail="请求体必须是 JSON 对象")

    upstream = await _send(
        request,
        user,
        method="POST",
        path="/api/v1/documents",
        body=json.dumps(adapt.create_payload_to_ms(body), ensure_ascii=False).encode("utf-8"),
        headers={"content-type": "application/json"},
    )
    if upstream.status_code >= 400:
        return _upstream_error(upstream)
    return _gateway_json(
        adapt.envelope(adapt.to_gateway_document(_json_body(upstream))),
        status_code=upstream.status_code,
    )


async def _upload_document(request: Request, user: User) -> Response:
    """网关 `/documents/upload`（multipart）→ 微服务 `/upload/multipart`，并保持「上传即解析」。

    请求体是流式转发的：大文件不会在网关里先读成一个大 bytes。
    """
    upstream_path = adapt.upload_path_to_ms(request.url.path)
    target = settings.DOCUMENT_SERVICE_URL.rstrip("/") + upstream_path
    headers = _build_headers(request, user, "POST", upstream_path)

    client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, read=300.0))
    try:
        upstream_request = client.build_request(
            "POST", target, content=request.stream(), headers=headers
        )
        upstream = await client.send(upstream_request)
    except httpx.RequestError as exc:
        await client.aclose()
        logger.warning("proxy upload to document-service failed: %s (%s)", target, exc)
        raise HTTPException(
            status_code=502,
            detail=f"document-service 不可达（{settings.DOCUMENT_SERVICE_URL}）：{exc}",
        )
    await client.aclose()

    if upstream.status_code >= 400:
        return _upstream_error(upstream)

    doc = _json_body(upstream)
    # 网关原本上传后就解析；转发模式下补一次 /process，行为保持一致（失败不阻塞上传）。
    processed = await _send(
        request,
        user,
        method="POST",
        path=f"/api/v1/documents/{doc['id']}/process",
        body=None,
    )
    if processed.status_code >= 400:
        logger.warning("proxy upload processed failed: %s", processed.text[:200])

    # 解析在微服务侧完成，通知仍由网关统一发（开关打开时 notify 会转发给 notification-service）
    await _notify_upload_processed(user, doc, processed)

    return _gateway_json(adapt.envelope(adapt.to_file_upload_response(doc)), status_code=201)


async def _notify_upload_processed(user: User, doc: dict, processed) -> None:
    """把「上传即解析」的结果写一条通知；解析失败也是通知（否则用户只看到状态变了）。"""
    title = doc.get("title") or doc.get("filename") or "文档"
    data = {
        "document_id": doc.get("id"),
        "knowledge_base_id": doc.get("knowledge_base_id"),
        "event": "document.processed",
    }
    if processed.status_code >= 400:
        detail = processed.text[:200]
        await notify(
            tenant_id=user.tenant_id,
            user_id=user.id,
            type=NotificationType.WARNING,
            title=f"《{title}》解析失败",
            content=f"document-service 返回 {processed.status_code}：{detail}",
            data={**data, "event": "document.failed"},
        )
        return

    body = _json_body(processed) or {}
    chunk_count = body.get("chunk_count") if isinstance(body, dict) else None
    await notify(
        tenant_id=user.tenant_id,
        user_id=user.id,
        type=NotificationType.SUCCESS,
        title=f"《{title}》解析完成",
        content=(
            f"已生成 {chunk_count} 个分块，可以在知识库里检索了。"
            if chunk_count
            else "文档已解析完成，可以在知识库里检索了。"
        ),
        data=data,
    )


async def _get_or_update_document(request: Request, user: User, doc_id: str) -> Response:
    method = request.method
    body = None
    if method in ("PATCH", "PUT"):
        try:
            payload = json.loads(await request.body() or b"{}")
        except (ValueError, json.JSONDecodeError):
            raise HTTPException(status_code=422, detail="请求体必须是 JSON 对象")
        body = json.dumps(adapt.update_payload_to_ms(payload), ensure_ascii=False).encode("utf-8")

    upstream = await _send(
        request,
        user,
        method=method,
        path=f"/api/v1/documents/{doc_id}",
        body=body,
        headers={"content-type": "application/json"} if body else None,
    )
    if upstream.status_code >= 400:
        return _upstream_error(upstream)
    if method == "DELETE":
        # 网关的 delete 返回 200 + 信封（微服务是 204），前端依赖 res.data
        return _gateway_json(adapt.envelope(None))
    return _gateway_json(adapt.envelope(adapt.to_gateway_document(_json_body(upstream))))


async def _reprocess_document(request: Request, user: User, doc_id: str) -> Response:
    upstream = await _send(
        request,
        user,
        method="POST",
        path=adapt.reprocess_path_to_ms(request.url.path),
        body=await request.body() or None,
        headers={"content-type": "application/json"},
    )
    if upstream.status_code >= 400:
        return _upstream_error(upstream)
    return _gateway_json(adapt.envelope(_json_body(upstream)))


_DOC_UUID_HELP = (
    "网关的文档分块存在网关自己的库；转发模式下 document-service 不提供 /chunks。"
    "请关闭 GATEWAY_PROXY_DOCUMENTS 查看分块，或等分块接口迁到 rag-service 后再开放。"
)


async def _dispatch_documents(request: Request, user: User) -> Response:
    path = request.url.path.rstrip("/") or "/api/v1/documents"
    method = request.method.upper()
    _require_permission(user, _document_permission(method, path))

    if path == "/api/v1/documents" and method == "GET":
        return await _list_documents(request, user)
    if path == "/api/v1/documents" and method == "POST":
        return await _create_document(request, user)
    if path == "/api/v1/documents/upload" and method == "POST":
        return await _upload_document(request, user)

    if path.startswith("/api/v1/documents/"):
        rest = path[len("/api/v1/documents/") :]
        doc_id, _, suffix = rest.partition("/")
        if suffix == "chunks" and method == "GET":
            return _gateway_json(
                adapt.error_envelope(_DOC_UUID_HELP, code="NOT_IMPLEMENTED"),
                status_code=501,
            )
        if suffix == "download" and method == "GET":
            # 网关的下载路径是 /documents/{id}/download，微服务是 /download/{id}；流式返回字节
            return await _forward_generic(
                request, user, path=f"/api/v1/download/{doc_id}"
            )
        if suffix == "reprocess" and method == "POST":
            return await _reprocess_document(request, user, doc_id)
        if not suffix and method in ("GET", "PATCH", "PUT", "DELETE"):
            return await _get_or_update_document(request, user, doc_id)

    return await _forward_generic(request, user)


# ============================================
# 路由（必须注册在网关自带的 documents 路由之前）
# ============================================


@router.api_route("/documents", methods=_METHODS, include_in_schema=False)
@router.api_route("/documents/{path:path}", methods=_METHODS, include_in_schema=False)
async def proxy_documents(request: Request, user: User = Depends(get_current_user)):
    return await _dispatch_documents(request, user)


@router.api_route("/upload/{path:path}", methods=_METHODS, include_in_schema=False)
async def proxy_upload(request: Request, user: User = Depends(get_current_user)):
    _require_permission(user, "document:create")
    return await _forward_generic(request, user)


@router.api_route("/download/{path:path}", methods=_METHODS, include_in_schema=False)
async def proxy_download(request: Request, user: User = Depends(get_current_user)):
    _require_permission(user, "document:read")
    return await _forward_generic(request, user)
