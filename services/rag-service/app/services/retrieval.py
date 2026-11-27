import time
from typing import Optional
from uuid import UUID

import cohere
from sqlalchemy import select

from app.core.config import settings
from app.core.errors import EmbeddingUnavailable
from app.models import DocumentChunk, Document, KnowledgeBase
from app.db.session import session_context
from app.services.document_processor import BM25Indexer, get_bm25_indexer


class RetrievalService:
    """Hybrid retrieval: BM25 + Vector with RRF fusion + Cohere Rerank."""

    def __init__(self):
        self.cohere_client = None
        self._bm25_cache: dict[UUID, BM25Indexer] = {}

    def _get_cohere_client(self):
        if self.cohere_client is None and settings.COHERE_API_KEY:
            self.cohere_client = cohere.AsyncClient(api_key=settings.COHERE_API_KEY)
        return self.cohere_client

    def _get_bm25_indexer(self, kb_id: UUID) -> BM25Indexer:
        # 与 DocumentProcessor 共享同一个实例：入库重建索引后这里立即生效
        indexer = get_bm25_indexer(kb_id)
        self._bm25_cache[kb_id] = indexer
        return indexer

    async def _rebuild_bm25(self, kb_id: UUID, indexer: BM25Indexer) -> None:
        """进程重启/冷启动时，从数据库重建 BM25 索引（否则关键词分支永远为空）。"""
        async with session_context() as session:
            rows = (
                await session.execute(
                    select(DocumentChunk.id, DocumentChunk.content)
                    .where(DocumentChunk.knowledge_base_id == kb_id)
                    .order_by(DocumentChunk.chunk_index)
                )
            ).all()
        indexer.build([(row[0], row[1]) for row in rows])

    async def retrieve(
        self,
        query: str,
        kb_id: UUID,
        tenant_id: UUID,
        top_k: Optional[int] = None,
        use_rerank: bool = True,
        filters: Optional[dict] = None,
    ) -> dict:
        """Hybrid retrieval with RRF fusion and optional rerank."""
        start_time = time.perf_counter()

        kb = await self._get_knowledge_base(kb_id)
        if not kb:
            raise ValueError(f"KnowledgeBase {kb_id} not found")

        final_k = top_k or kb.retrieval_final_k
        retrieval_k = kb.retrieval_top_k

        # 1. Vector search（用知识库自己的 embedding 模型，和入库时保持一致）
        degraded = False
        degraded_reason = None
        try:
            vector_results = await self._vector_search(
                query, kb_id, tenant_id, retrieval_k, filters, kb.embedding_model
            )
        except EmbeddingUnavailable as exc:
            # embedding 不可用：不直接 500/503 把搜索打死，先看关键词分支能不能命中
            vector_results = []
            degraded = True
            degraded_reason = exc.public_message()
        vector_time = time.perf_counter()

        # 2. BM25 search
        bm25_results = await self._bm25_search(query, kb_id, retrieval_k)
        bm25_time = time.perf_counter()

        # 3. RRF Fusion
        fused_results = self._rrf_fusion(vector_results, bm25_results, kb.rrf_k, final_k * 2)
        fusion_time = time.perf_counter()

        # 4. Optional Cohere Rerank
        rerank_time = None
        if use_rerank and settings.COHERE_API_KEY and fused_results:
            fused_results = await self._rerank(query, fused_results, settings.RERANK_TOP_K)
            rerank_time = time.perf_counter() - fusion_time
            fused_results = fused_results[:final_k]
        else:
            fused_results = fused_results[:final_k]

        total_time = time.perf_counter() - start_time

        return {
            "chunks": fused_results,
            "degraded": degraded,
            "degraded_reason": degraded_reason,
            "total_found": len(fused_results),
            "retrieval_time_ms": (vector_time - start_time) * 1000,
            "bm25_time_ms": (bm25_time - vector_time) * 1000,
            "fusion_time_ms": (fusion_time - bm25_time) * 1000,
            "rerank_time_ms": rerank_time * 1000 if rerank_time else None,
            "total_time_ms": total_time * 1000,
        }

    async def _get_knowledge_base(self, kb_id: UUID) -> Optional[KnowledgeBase]:
        async with session_context() as session:
            return await session.get(KnowledgeBase, kb_id)

    async def _vector_search(
        self,
        query: str,
        kb_id: UUID,
        tenant_id: UUID,
        top_k: int,
        filters: Optional[dict],
        model: Optional[str] = None,
    ) -> list[dict]:
        """Vector similarity search using pgvector."""
        # Get query embedding
        query_embedding = await self._embed_query(query, model)
        if not query_embedding:
            return []

        async with session_context() as session:
            stmt = (
                select(
                    DocumentChunk.id,
                    DocumentChunk.document_id,
                    DocumentChunk.content,
                    DocumentChunk.meta,
                    Document.filename.label("document_filename"),
                    (1 - DocumentChunk.embedding.cosine_distance(query_embedding)).label("score"),
                )
                .join(Document, DocumentChunk.document_id == Document.id)
                .where(
                    DocumentChunk.knowledge_base_id == kb_id,
                    DocumentChunk.tenant_id == tenant_id,
                    DocumentChunk.embedding.is_not(None),
                )
                .order_by(DocumentChunk.embedding.cosine_distance(query_embedding))
                .limit(top_k)
            )

            # Apply filters if any
            if filters:
                for key, value in filters.items():
                    if hasattr(DocumentChunk, key):
                        stmt = stmt.where(getattr(DocumentChunk, key) == value)

            result = await session.execute(stmt)
            rows = result.all()

            return [
                {
                    "chunk_id": row.id,
                    "document_id": row.document_id,
                    "document_filename": row.document_filename,
                    "content": row.content,
                    "score": float(row.score),
                    "metadata": row.meta,
                    "source": "vector",
                }
                for row in rows
            ]

    async def _bm25_search(
        self,
        query: str,
        kb_id: UUID,
        top_k: int,
    ) -> list[dict]:
        """BM25 keyword search."""
        indexer = self._get_bm25_indexer(kb_id)
        if indexer.bm25 is None:
            await self._rebuild_bm25(kb_id, indexer)
        results = indexer.search(query, top_k)

        if not results:
            return []

        # Fetch chunk details from DB
        chunk_ids = [r[0] for r in results]
        async with session_context() as session:
            stmt = (
                select(
                    DocumentChunk.id,
                    DocumentChunk.document_id,
                    DocumentChunk.content,
                    DocumentChunk.meta,
                    Document.filename.label("document_filename"),
                )
                .join(Document, DocumentChunk.document_id == Document.id)
                .where(DocumentChunk.id.in_(chunk_ids))
            )
            result = await session.execute(stmt)
            chunks_map = {row.id: row for row in result.all()}

        scored_results = []
        for chunk_id, score in results:
            if chunk_id in chunks_map:
                row = chunks_map[chunk_id]
                scored_results.append(
                    {
                        "chunk_id": row.id,
                        "document_id": row.document_id,
                        "document_filename": row.document_filename,
                        "content": row.content,
                        "score": float(score),
                        "metadata": row.meta,
                        "source": "bm25",
                    }
                )
        return scored_results

    def _rrf_fusion(
        self,
        vector_results: list[dict],
        bm25_results: list[dict],
        k: int,
        final_k: int,
    ) -> list[dict]:
        """Reciprocal Rank Fusion."""
        scores: dict[UUID, float] = {}
        chunk_map: dict[UUID, dict] = {}

        # Vector ranks
        for rank, result in enumerate(vector_results):
            chunk_id = result["chunk_id"]
            scores[chunk_id] = scores.get(chunk_id, 0) + 1.0 / (k + rank + 1)
            chunk_map[chunk_id] = result

        # BM25 ranks
        for rank, result in enumerate(bm25_results):
            chunk_id = result["chunk_id"]
            scores[chunk_id] = scores.get(chunk_id, 0) + 1.0 / (k + rank + 1)
            if chunk_id not in chunk_map:
                chunk_map[chunk_id] = result

        # Sort by fused score
        sorted_chunks = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:final_k]

        fused = []
        for chunk_id, score in sorted_chunks:
            result = chunk_map[chunk_id].copy()
            result["score"] = score
            result["source"] = "hybrid"
            fused.append(result)

        return fused

    async def _rerank(
        self,
        query: str,
        candidates: list[dict],
        top_k: int,
    ) -> list[dict]:
        """Cohere rerank."""
        client = self._get_cohere_client()
        if not client:
            return candidates

        documents = [c["content"] for c in candidates]
        try:
            response = await client.rerank(
                model=settings.RERANK_MODEL,
                query=query,
                documents=documents,
                top_n=min(top_k, len(documents)),
                return_documents=False,
            )

            reranked = []
            for r in response.results:
                candidate = candidates[r.index].copy()
                candidate["score"] = r.relevance_score
                candidate["source"] = "reranked"
                reranked.append(candidate)
            return reranked
        except Exception:
            # Fallback to original order on error
            return candidates

    async def _embed_query(self, query: str, model: Optional[str] = None) -> Optional[list[float]]:
        """Generate embedding for query（默认用 KB 的模型，未指定则用全局默认）。"""
        from openai import AsyncOpenAI

        model_name = model or settings.EMBEDDING_MODEL
        try:
            client = AsyncOpenAI(
                api_key=settings.EMBEDDING_API_KEY,
                base_url=settings.EMBEDDING_API_BASE,
            )
            response = await client.embeddings.create(
                model=model_name,
                input=[query],
                dimensions=settings.EMBEDDING_DIM if "3-" in model_name else None,
            )
            return response.data[0].embedding
        except Exception as exc:  # noqa: BLE001 - 统一映射成 503 / 降级
            raise EmbeddingUnavailable(
                f"{type(exc).__name__}: {str(exc)[:200]}", model=model_name
            ) from exc