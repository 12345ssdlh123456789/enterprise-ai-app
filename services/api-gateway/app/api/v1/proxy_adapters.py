"""网关契约 ↔ document-service 契约转换（仅转发模式使用）。

网关的文档接口对外是 `{success, data}` 信封 + `file_name` / `mime_type` / `type` 等字段；
document-service 是裸对象 + `filename` / `original_filename` / `document_type`。
前端（apps/web/lib/api.ts）按网关契约实现，所以转发时必须在这里转换，
否则开关一开，工作台的文档页会拿到对不上的字段。

这个模块只做纯数据转换，不碰 HTTP，方便单独验证。
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import uuid4

# 微服务的 document_type 是 pdf/docx/txt...，网关/前端用大写枚举
_DOC_TYPE_UPPER = {
    "pdf": "PDF",
    "docx": "DOCX",
    "markdown": "MARKDOWN",
    "md": "MARKDOWN",
    "html": "HTML",
    "txt": "TXT",
    "text": "TXT",
    "csv": "CSV",
    "json": "JSON",
    "pptx": "PPTX",
    "xlsx": "XLSX",
    "image": "IMAGE",
    "other": "OTHER",
}


def envelope(data: Any = None, *, success: bool = True) -> dict:
    """网关的 ApiResponse 形状（前端只读 data，error 用于失败）。"""
    return {"success": success, "data": data, "error": None, "meta": None}


def error_envelope(message: str, code: str = "UPSTREAM_ERROR") -> dict:
    return {
        "success": False,
        "data": None,
        "error": {"code": code, "message": message, "details": None},
        "meta": None,
    }


def _doc_type(raw: Optional[str], filename: str = "") -> str:
    value = (raw or "").lower()
    if value in _DOC_TYPE_UPPER:
        return _DOC_TYPE_UPPER[value]
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return _DOC_TYPE_UPPER.get(ext, "OTHER")


def to_gateway_document(doc: dict) -> dict:
    """document-service 的 DocumentRead → 网关 DocumentResponse。"""
    filename = doc.get("original_filename") or doc.get("filename") or ""
    return {
        "id": doc.get("id"),
        "knowledge_base_id": doc.get("knowledge_base_id"),
        "tenant_id": doc.get("tenant_id"),
        "title": filename,
        "source_url": None,
        "file_name": doc.get("filename"),
        "file_size": doc.get("file_size"),
        "mime_type": doc.get("content_type"),
        "type": _doc_type(doc.get("document_type"), filename),
        "status": str(doc.get("status") or "").lower(),
        "chunk_count": doc.get("chunk_count") or 0,
        "token_count": doc.get("token_count") or 0,
        "error_message": doc.get("error_message"),
        "metadata": doc.get("meta") or doc.get("metadata") or {},
        "created_by": doc.get("created_by"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
        "processed_at": doc.get("processed_at"),
    }


def to_gateway_list_item(doc: dict) -> dict:
    """document-service 的 DocumentRead → 网关 DocumentListItem。"""
    filename = doc.get("original_filename") or doc.get("filename") or ""
    return {
        "id": doc.get("id"),
        "title": filename,
        "file_name": doc.get("filename"),
        "type": _doc_type(doc.get("document_type"), filename),
        "status": str(doc.get("status") or "").lower(),
        "file_size": doc.get("file_size"),
        "mime_type": doc.get("content_type"),
        "chunk_count": doc.get("chunk_count") or 0,
        "token_count": doc.get("token_count") or 0,
        "created_at": doc.get("created_at"),
    }


def to_file_upload_response(doc: dict) -> dict:
    """document-service 的上传结果 → 网关 FileUploadResponse。"""
    doc_id = doc.get("id")
    return {
        "file_id": doc_id,
        "file_name": doc.get("filename") or doc.get("original_filename"),
        "file_size": doc.get("file_size") or 0,
        "mime_type": doc.get("content_type") or "",
        "url": f"/api/v1/documents/{doc_id}/download",
    }


def to_gateway_notification(notif: dict) -> dict:
    """notification-service 的通知 → 网关 NotificationSchema 字段。

    第 26 轮起两侧契约一致（UUID 主键、user_id / title / data / read 同名），
    这里只做「缺省值兜底」，不再伪造 ID。
    """
    return {
        "id": notif.get("id"),
        "tenant_id": notif.get("tenant_id"),
        "user_id": notif.get("user_id"),
        "type": notif.get("type") or "INFO",
        "channel": notif.get("channel") or "IN_APP",
        "title": notif.get("title") or "",
        "content": notif.get("content") or "",
        "data": notif.get("data"),
        "read": bool(notif.get("read")),
        "sent_at": notif.get("sent_at"),
        "created_at": notif.get("created_at"),
    }


def notification_create_payload_to_ms(body: dict) -> dict:
    """网关 NotificationCreate → 微服务 NotificationCreate（同名，只挑存在的键）。"""
    payload = {}
    for key in ("user_id", "type", "channel", "title", "content", "data"):
        if body.get(key) is not None:
            payload[key] = body[key]
    if "title" not in payload and body.get("content"):
        payload["title"] = str(body["content"]).strip().splitlines()[0][:255] or "通知"
    return payload


def paginated(items: list[dict], total: int, page: int, page_size: int) -> dict:
    total_pages = (total + page_size - 1) // page_size if page_size else 0
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


def create_payload_to_ms(body: dict) -> dict:
    """网关 DocumentCreate → document-service DocumentCreate。

    网关：{title, type, file_name, file_size, mime_type, metadata:{file_hash}}
    微服务：{filename, original_filename, content_type, file_size, file_hash, knowledge_base_id, metadata}
    """
    filename = body.get("file_name") or body.get("title") or "untitled"
    metadata = body.get("metadata") or {}
    return {
        "knowledge_base_id": body.get("knowledge_base_id"),
        # 微服务不做 KB 归属校验，这里保留原值；没有 KB 时让入库步骤自行跳过
        "filename": filename,
        "original_filename": body.get("title") or filename,
        "content_type": body.get("mime_type") or "application/octet-stream",
        "file_size": body.get("file_size") or 0,
        "file_hash": metadata.get("file_hash") or uuid4().hex,
        "metadata": metadata,
    }


def update_payload_to_ms(body: dict) -> dict:
    """网关 DocumentUpdate（title / metadata）→ 微服务 DocumentUpdate（filename / metadata）。"""
    payload: dict = {}
    if body.get("title"):
        payload["filename"] = body["title"]
    if "metadata" in body:
        payload["metadata"] = body["metadata"]
    return payload


# ============================================
# 工作流：网关定义 ↔ workflow-service 定义
# ============================================
# 网关节点：{id, type(大写), name, position, config, inputs[{id,name,type,required}], outputs[]}
# 微服务节点：{id, type(小写), position, config, inputs[str], outputs[str]}（没有 name，靠 config.name 保存）
# 网关边：{id, source_node_id, source_port_id, target_node_id, target_port_id}
# 微服务边：{id, source, target, source_handle, target_handle}


def workflow_definition_to_ms(definition: dict) -> dict:
    nodes = []
    for node in definition.get("nodes") or []:
        config = dict(node.get("config") or {})
        if node.get("name"):
            config.setdefault("name", node["name"])
        nodes.append(
            {
                "id": node.get("id"),
                "type": str(node.get("type") or "").lower(),
                "position": node.get("position") or {"x": 0, "y": 0},
                "config": config,
                "inputs": [p.get("id") for p in (node.get("inputs") or []) if p.get("id")],
                "outputs": [p.get("id") for p in (node.get("outputs") or []) if p.get("id")],
            }
        )
    edges = [
        {
            "id": edge.get("id"),
            "source": edge.get("source_node_id") or edge.get("source"),
            "target": edge.get("target_node_id") or edge.get("target"),
            "source_handle": edge.get("source_port_id"),
            "target_handle": edge.get("target_port_id"),
        }
        for edge in definition.get("edges") or []
    ]
    return {"nodes": nodes, "edges": edges}


def workflow_definition_to_gateway(definition: dict) -> dict:
    nodes = []
    for node in definition.get("nodes") or []:
        config = node.get("config") or {}
        nodes.append(
            {
                "id": node.get("id"),
                "type": str(node.get("type") or "").upper(),
                "name": config.get("name") or node.get("id") or "",
                "position": node.get("position") or {"x": 0, "y": 0},
                "config": config,
                "inputs": [
                    {"id": port, "name": port, "type": "string", "required": False}
                    for port in node.get("inputs") or []
                ],
                "outputs": [
                    {"id": port, "name": port, "type": "string", "required": False}
                    for port in node.get("outputs") or []
                ],
            }
        )
    edges = [
        {
            "id": edge.get("id"),
            "source_node_id": edge.get("source") or edge.get("source_node_id"),
            "source_port_id": edge.get("source_handle") or "",
            "target_node_id": edge.get("target") or edge.get("target_node_id"),
            "target_port_id": edge.get("target_handle") or "",
        }
        for edge in definition.get("edges") or []
    ]
    return {"nodes": nodes, "edges": edges}


def to_gateway_workflow(wf: dict) -> dict:
    return {
        "id": wf.get("id"),
        "tenant_id": wf.get("tenant_id"),
        "name": wf.get("name"),
        "description": wf.get("description"),
        "definition": workflow_definition_to_gateway(wf.get("definition") or {}),
        "status": str(wf.get("status") or "").upper(),
        "version": wf.get("version") or 1,
        "created_by": wf.get("created_by"),
        "created_at": wf.get("created_at"),
        "updated_at": wf.get("updated_at"),
        "published_at": wf.get("published_at"),
    }


def to_gateway_workflow_item(wf: dict) -> dict:
    return {
        "id": wf.get("id"),
        "name": wf.get("name"),
        "description": wf.get("description"),
        "status": str(wf.get("status") or "").upper(),
        "version": wf.get("version") or 1,
        "created_at": wf.get("created_at"),
        "updated_at": wf.get("updated_at"),
    }


def workflow_create_payload_to_ms(body: dict) -> dict:
    return {
        "name": body.get("name"),
        "description": body.get("description"),
        "definition": workflow_definition_to_ms(body.get("definition") or {}),
    }


def workflow_update_payload_to_ms(body: dict) -> dict:
    payload: dict = {}
    for field in ("name", "description"):
        if field in body:
            payload[field] = body[field]
    if "definition" in body:
        payload["definition"] = workflow_definition_to_ms(body["definition"] or {})
    if body.get("status"):
        payload["status"] = str(body["status"]).lower()
    return payload


def to_gateway_execution(result: dict, *, workflow_id, tenant_id) -> dict:
    return {
        "id": result.get("execution_id"),
        "workflow_id": workflow_id,
        "tenant_id": tenant_id,
        "status": result.get("status"),
        "input": result.get("input") or {},  # 微服务不回显输入
        "output": result.get("output_data"),
        "error": result.get("error_message"),
        "started_at": result.get("started_at"),
        "completed_at": result.get("completed_at"),
        # 微服务的节点级日志在 /executions/{id}/logs，这里不额外拉取
        "node_executions": [],
    }


def to_gateway_execution_record(execution: dict) -> dict:
    return {
        "id": execution.get("id"),
        "workflow_id": execution.get("workflow_id"),
        "tenant_id": execution.get("tenant_id"),
        "status": execution.get("status"),
        "input": execution.get("input_data") or {},
        "output": execution.get("output_data"),
        "error": execution.get("error_message"),
        "started_at": execution.get("started_at") or execution.get("created_at"),
        "completed_at": execution.get("completed_at"),
        "node_executions": [],
    }


def upload_path_to_ms(path: str) -> str:
    """/api/v1/documents/upload（网关）→ /api/v1/upload/multipart（微服务）。"""
    return "/api/v1/upload/multipart"


def reprocess_path_to_ms(path: str) -> str:
    """.../reprocess（网关）→ .../process（微服务）。"""
    return path[: -len("/reprocess")] + "/process"
