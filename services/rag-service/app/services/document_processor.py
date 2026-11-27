import tiktoken
from datetime import datetime
from typing import Optional
from uuid import UUID

from rank_bm25 import BM25Plus

from app.core.config import settings
from app.core.errors import EmbeddingUnavailable
from app.models import Document, DocumentChunk, DocumentStatus, KnowledgeBase
from app.db.session import session_context


class Tokenizer:
    """Token counting and text splitting using tiktoken."""

    def __init__(self, model: str = "cl100k_base"):
        self.encoding = tiktoken.get_encoding(model)

    def count_tokens(self, text: str) -> int:
        return len(self.encoding.encode(text))

    def split_text(self, text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
        """Split text into overlapping chunks by token count."""
        tokens = self.encoding.encode(text)
        if len(tokens) <= chunk_size:
            return [text]

        chunks = []
        start = 0
        while start < len(tokens):
            end = min(start + chunk_size, len(tokens))
            chunk_tokens = tokens[start:end]
            chunks.append(self.encoding.decode(chunk_tokens))
            if end == len(tokens):
                break
            start = end - chunk_overlap
        return chunks


class DocumentProcessor:
    """Process documents: parse, chunk, embed, and store."""

    def __init__(self):
        self.tokenizer = Tokenizer()
        self.embedding_client = None  # lazy init

    def _get_embedding_client(self):
        if self.embedding_client is None:
            from openai import AsyncOpenAI

            # 缺 key / base_url 不合法时 AsyncOpenAI 在构造阶段就抛错，
            # 必须同样映射成 EmbeddingUnavailable，否则会变成 500 而不是约定的 503。
            try:
                self.embedding_client = AsyncOpenAI(
                    api_key=settings.EMBEDDING_API_KEY,
                    base_url=settings.EMBEDDING_API_BASE,
                )
            except Exception as exc:  # noqa: BLE001
                raise EmbeddingUnavailable(
                    f"{type(exc).__name__}: {str(exc)[:200]}",
                    model=settings.EMBEDDING_MODEL,
                ) from exc
        return self.embedding_client

    async def process_document(self, document_id: UUID, force_reprocess: bool = False) -> dict:
        """Main entry point to process a document."""
        async with session_context() as session:
            doc = await session.get(Document, document_id)
            if not doc:
                raise ValueError(f"Document {document_id} not found")

            if doc.status == DocumentStatus.COMPLETED and not force_reprocess:
                return {"status": "already_completed", "chunks_created": doc.chunk_count}

            doc.status = DocumentStatus.PROCESSING
            await session.flush()

            try:
                kb = await session.get(KnowledgeBase, doc.knowledge_base_id)
                if not kb:
                    raise ValueError(f"KnowledgeBase {doc.knowledge_base_id} not found")

                # Extract text content (placeholder - real impl would parse file)
                text_content = await self._extract_text(doc)

                # Chunk
                chunks = self._chunk_text(text_content, kb.chunk_size, kb.chunk_overlap)

                # Embed
                embeddings = await self._embed_chunks(chunks, kb.embedding_model)

                # Store chunks
                await self._store_chunks(session, doc, kb, chunks, embeddings)

                # Update document
                doc.status = DocumentStatus.COMPLETED
                doc.chunk_count = len(chunks)
                doc.token_count = sum(self.tokenizer.count_tokens(c) for c in chunks)
                doc.completed_at = datetime.utcnow()

                await session.commit()

                # 刷新 BM25 索引（混合检索的关键词分支）
                # 索引失败不应把已经成功的文档标成失败，只降级关键词检索
                try:
                    await self._update_bm25_index(kb.id)
                except Exception:  # noqa: BLE001
                    pass

                return {"status": "completed", "chunks_created": len(chunks)}

            except Exception as e:
                doc.status = DocumentStatus.FAILED
                doc.error_message = str(e)
                await session.commit()
                raise

    async def _extract_text(self, doc: Document) -> str:
        """取出待处理正文。

        上游（document-service 解析后回调 / 前端直传）会把正文放在 `metadata.text`，
        有正文就用正文；没有则退化为占位文本。注意：退化为占位文本时只能验证
        分块 / 嵌入 / 检索链路，不能声称解析了真实文件（真实解析在 document-service）。
        """
        text = (doc.meta or {}).get("text")
        if isinstance(text, str) and text.strip():
            return text
        return (
            f"Document content for {doc.original_filename}. "
            "This is placeholder text that would be extracted from the actual file."
        )

    def _chunk_text(self, text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
        """Split text into chunks."""
        return self.tokenizer.split_text(text, chunk_size, chunk_overlap)

    async def _embed_chunks(self, chunks: list[str], model: str) -> list[list[float]]:
        """Generate embeddings for chunks."""
        client = self._get_embedding_client()

        # Process in batches
        all_embeddings = []
        for i in range(0, len(chunks), settings.EMBEDDING_BATCH_SIZE):
            batch = chunks[i : i + settings.EMBEDDING_BATCH_SIZE]
            try:
                response = await client.embeddings.create(
                    model=model,
                    input=batch,
                    dimensions=settings.EMBEDDING_DIM if "3-" in model else None,
                )
            except Exception as exc:  # noqa: BLE001 - 统一映射成 503
                raise EmbeddingUnavailable(
                    f"{type(exc).__name__}: {str(exc)[:200]}", model=model
                ) from exc
            all_embeddings.extend([e.embedding for e in response.data])
        return all_embeddings

    async def _store_chunks(
        self,
        session,
        doc: Document,
        kb: KnowledgeBase,
        chunks: list[str],
        embeddings: list[list[float]],
    ) -> None:
        """Store chunks with embeddings."""
        for idx, (content, embedding) in enumerate(zip(chunks, embeddings)):
            chunk = DocumentChunk(
                knowledge_base_id=kb.id,
                document_id=doc.id,
                tenant_id=doc.tenant_id,
                chunk_index=idx,
                content=content,
                token_count=self.tokenizer.count_tokens(content),
                embedding=embedding,
                metadata={},
            )
            session.add(chunk)

    async def _update_bm25_index(self, kb_id: UUID) -> None:
        """用知识库当前的全部分块重建 BM25 索引，并刷新进程内缓存。

        之前这里是个 `pass`（调用点也被注释掉），所以混合检索的关键词分支永远为空。
        """
        from sqlalchemy import select

        async with session_context() as session:
            rows = (
                await session.execute(
                    select(DocumentChunk.id, DocumentChunk.content)
                    .where(DocumentChunk.knowledge_base_id == kb_id)
                    .order_by(DocumentChunk.chunk_index)
                )
            ).all()

        get_bm25_indexer(kb_id).build([(row[0], row[1]) for row in rows])


class BM25Indexer:
    """BM25 index for keyword search."""

    def __init__(self, kb_id: UUID):
        self.kb_id = kb_id
        # v3：分词策略（中文按字切）+ 打分器（BM25Plus）都变过，旧索引文件直接换名，冷启动自动重建
        self.index_path = f"{settings.BM25_INDEX_PATH}/{kb_id}_v3.pkl"
        # BM25Plus 的 IDF 恒为正；BM25Okapi 在单文档知识库上会给全部分数负值
        self.bm25: Optional[BM25Plus] = None
        self.chunk_ids: list[UUID] = []
        self.corpus: list[list[str]] = []

    def build(self, chunks: list[tuple[UUID, str]]) -> None:
        """Build BM25 index from chunks."""
        self.chunk_ids = [c[0] for c in chunks]
        self.corpus = [self._tokenize(c[1]) for c in chunks]
        # 空语料会抛异常；没有分块时置空并跳过落盘
        self.bm25 = BM25Plus(self.corpus) if self.corpus else None
        if self.bm25 is not None:
            self._save()

    def _tokenize(self, text: str) -> list[str]:
        r"""BM25 分词：英文/数字按词，中文按单字 + 相邻二字。

        原来用 `\w+`，中文整段会被当成一个 token（中文没有空格），
        导致查询词和语料永远不重叠、关键词分支对中文实际不可用。
        """
        import re

        lower = text.lower()
        tokens = re.findall(r"[a-z0-9_]+", lower)
        for run in re.findall(r"[\u4e00-\u9fff]+", lower):
            tokens.extend(run)
            tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
        return tokens

    def search(self, query: str, top_k: int = 20) -> list[tuple[UUID, float]]:
        """Search BM25 index."""
        if not self.bm25:
            self._load()
        if not self.bm25:
            return []

        tokenized_query = self._tokenize(query)
        scores = self.bm25.get_scores(tokenized_query)
        top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
        return [(self.chunk_ids[i], scores[i]) for i in top_indices if scores[i] > 0]

    def _save(self) -> None:
        """Save index to disk."""
        import pickle
        import os
        os.makedirs(os.path.dirname(self.index_path), exist_ok=True)
        with open(self.index_path, "wb") as f:
            pickle.dump({"chunk_ids": self.chunk_ids, "corpus": self.corpus}, f)

    def _load(self) -> None:
        """Load index from disk."""
        import pickle
        import os
        if os.path.exists(self.index_path):
            with open(self.index_path, "rb") as f:
                data = pickle.load(f)
                self.chunk_ids = data["chunk_ids"]
                self.corpus = data["corpus"]
                self.bm25 = BM25Plus(self.corpus) if self.corpus else None


_BM25_CACHE: dict[UUID, "BM25Indexer"] = {}


def get_bm25_indexer(kb_id: UUID) -> "BM25Indexer":
    """进程内共享的 BM25 索引实例：入库重建后，检索侧能立刻看到新分块。"""
    if kb_id not in _BM25_CACHE:
        _BM25_CACHE[kb_id] = BM25Indexer(kb_id)
    return _BM25_CACHE[kb_id]