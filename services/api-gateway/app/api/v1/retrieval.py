"""检索路由：在指定知识库的文档分块中做轻量关键词检索。

本地部署没有独立向量库，这里用词/二字切片重合度打分，
返回结构与 rag-service 的 /retrieval/search 保持一致，前端引用面板可直接渲染。
"""

import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import get_current_tenant, get_current_user
from app.db.session import get_async_db
from app.models import Document, DocumentChunk, KnowledgeBase, Tenant, User
from app.schemas import (
    ApiResponse,
    ResponseMeta,
    RetrievalResponseSchema,
    RetrievalSearchRequest,
    RetrievedChunkSchema,
)
from app.services.ingest import tokenize

router = APIRouter(prefix="/retrieval", tags=["Retrieval"])

MIN_SCORE = 0.05


def create_meta(request: Request) -> ResponseMeta:
    return ResponseMeta(
        request_id=getattr(request.state, "request_id", "unknown"),
        timestamp=datetime.now(timezone.utc),
        version=settings.APP_VERSION,
    )


def score_chunk(query: str, query_tokens: set[str], content: str) -> float:
    if not content:
        return 0.0
    matched = query_tokens.intersection(tokenize(content))
    coverage = len(matched) / len(query_tokens) if query_tokens else 0.0
    bonus = 0.15 if query and query.lower() in content.lower() else 0.0
    return min(1.0, coverage * 0.85 + bonus)


@router.post("/search", response_model=ApiResponse[RetrievalResponseSchema])
async def search(
    request: Request,
    body: RetrievalSearchRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """在知识库内检索与查询最相关的文档分块。"""
    started = time.perf_counter()

    kb_result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == body.knowledge_base_id,
            KnowledgeBase.tenant_id == current_tenant.id,
            KnowledgeBase.deleted_at.is_(None),
        )
    )
    kb = kb_result.scalar_one_or_none()
    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge base not found",
        )

    result = await db.execute(
        select(DocumentChunk, Document)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            DocumentChunk.knowledge_base_id == body.knowledge_base_id,
            Document.deleted_at.is_(None),
        )
    )
    rows = result.all()

    query = body.query.strip()
    query_tokens = set(tokenize(query))
    ranked = []
    for chunk, doc in rows:
        score = score_chunk(query, query_tokens, chunk.content)
        if score < MIN_SCORE:
            continue
        ranked.append((score, chunk, doc))

    ranked.sort(key=lambda item: item[0], reverse=True)
    top = ranked[: body.top_k]

    chunks = [
        RetrievedChunkSchema(
            chunk_id=str(chunk.id),
            document_id=str(doc.id),
            document_filename=doc.file_name or doc.title,
            content=chunk.content,
            score=round(score, 4),
            metadata={**(chunk.meta or {}), "title": doc.title, "sequence": chunk.sequence},
        )
        for score, chunk, doc in top
    ]

    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    return ApiResponse(
        data=RetrievalResponseSchema(
            query=query,
            chunks=chunks,
            total_found=len(ranked),
            retrieval_time_ms=elapsed_ms,
            rerank_time_ms=None,
        ),
        meta=create_meta(request),
    )
