"""网关本地的知识库检索（关键词打分）。

对话（`conversations.py`）和工作流的 RAG 节点（`workflow_runner.py`）共用这一份实现，
避免两套打分逻辑慢慢跑偏。真正的向量检索在 rag-service，这里只是默认单体模式下的可用替代。
"""

from __future__ import annotations

from typing import List
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, DocumentChunk
from app.services.ingest import tokenize


async def retrieve_chunks(
    db: AsyncSession,
    knowledge_base_id: UUID,
    query: str,
    top_k: int = 5,
    min_score: float = 0.05,
) -> List[dict]:
    """轻量关键词检索：按查询词与分块内容的重合度打分，返回前 top_k 个分块。"""
    result = await db.execute(
        select(DocumentChunk, Document)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            DocumentChunk.knowledge_base_id == knowledge_base_id,
            Document.deleted_at.is_(None),
        )
    )
    rows = result.all()
    if not rows:
        return []

    query_tokens = set(tokenize(query))
    ranked = []
    for chunk, doc in rows:
        matched = query_tokens.intersection(set(tokenize(chunk.content)))
        coverage = len(matched) / len(query_tokens) if query_tokens else 0.0
        bonus = 0.15 if query and query.lower() in chunk.content.lower() else 0.0
        score = min(1.0, coverage * 0.85 + bonus)
        if score < min_score:
            continue
        ranked.append((score, chunk, doc))

    ranked.sort(key=lambda item: item[0], reverse=True)
    top = ranked[:top_k]

    return [
        {
            "chunk_id": str(chunk.id),
            "document_id": str(doc.id),
            "document_filename": doc.file_name or doc.title,
            "content": chunk.content,
            "score": round(score, 4),
            "metadata": {**(chunk.meta or {}), "title": doc.title, "sequence": chunk.sequence},
        }
        for score, chunk, doc in top
    ]


def build_rag_context(chunks: List[dict]) -> str:
    """把检索到的分块拼成 RAG 上下文。"""
    if not chunks:
        return ""
    parts = []
    for i, c in enumerate(chunks, 1):
        parts.append(f"[引用{i}] {c['content']}")
    return "\n\n".join(parts)
