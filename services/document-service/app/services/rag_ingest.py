"""解析完成后把正文送进 rag-service（登记 + 分块 + 嵌入 + BM25 刷新）。

这是 P1「上传即入库」的最后一公里：以前调用方要手工在 rag-service 建文档、再调 /process，
现在 document-service 解析完自动完成，检索侧立刻能命中。

调用是 **best-effort**：rag-service 没起、签名不对、知识库不存在都不应该让上传失败，
只记日志并在响应里返回 `rag_ingested=false`。跨服务请求带第 6 轮的 HMAC 签名。
"""

from __future__ import annotations

import logging
from typing import Optional
from uuid import UUID

import httpx

from app.core.config import settings
from app.core.service_auth import sign_request

logger = logging.getLogger(__name__)

INGEST_PATH = "/api/v1/documents/ingest"


async def ingest_document_text(
    *,
    tenant_id: UUID,
    user_id: Optional[UUID],
    knowledge_base_id: Optional[UUID],
    title: str,
    text: str,
    file_hash: Optional[str] = None,
) -> dict | None:
    """返回 rag 的 IngestResponse；未启用 / 失败时返回 None（不抛异常）。"""
    if not settings.AUTO_INGEST_TO_RAG:
        return None
    if not knowledge_base_id:
        logger.info("skip rag ingest: document has no knowledge_base_id")
        return None
    if not (text or "").strip():
        logger.info("skip rag ingest: empty text")
        return None

    tenant = str(tenant_id)
    user = str(user_id) if user_id else ""
    headers = {"X-Tenant-Id": tenant, "Content-Type": "application/json"}
    if user:
        headers["X-User-Id"] = user
    headers.update(
        sign_request(
            settings.SERVICE_API_KEY,
            "POST",
            INGEST_PATH,
            tenant,
            user,
        )
    )

    url = f"{settings.RAG_SERVICE_URL.rstrip('/')}{INGEST_PATH}"
    payload = {
        "knowledge_base_id": str(knowledge_base_id),
        "title": title,
        "text": text,
        "file_hash": file_hash,
        "metadata": {"source": "document-service"},
    }

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(url, json=payload, headers=headers)
    except Exception as exc:  # noqa: BLE001 - 上游不可用不影响解析结果
        logger.warning("rag ingest failed (%s): %s", url, exc)
        return None

    if resp.status_code >= 400:
        logger.warning("rag ingest rejected (%s): %s %s", url, resp.status_code, resp.text[:200])
        return None

    try:
        body = resp.json()
    except ValueError:
        return None
    logger.info("rag ingest ok: %s", body)
    return body
