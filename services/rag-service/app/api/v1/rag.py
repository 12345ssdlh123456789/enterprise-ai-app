from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_session
from app.schemas import (
    KnowledgeBaseCreate,
    KnowledgeBaseRead,
    KnowledgeBaseUpdate,
    DocumentCreate,
    DocumentRead,
    DocumentChunkRead,
    RetrievalRequest,
    RetrievalResponse,
    RetrievedChunk,
    ProcessDocumentRequest,
    ProcessDocumentResponse,
    EmbeddingRequest,
    EmbeddingResponse,
    IngestRequest,
    IngestResponse,
)
from app.core.errors import EmbeddingUnavailable
from app.services.document_processor import DocumentProcessor
from app.services.retrieval import RetrievalService
from app.core.context import current_tenant_id

router = APIRouter(prefix="/knowledge-bases", tags=["Knowledge Bases"])

# Services (singletons)
doc_processor = DocumentProcessor()
retrieval_service = RetrievalService()


# Knowledge Base CRUD
@router.post("", response_model=KnowledgeBaseRead, status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(
    kb_in: KnowledgeBaseCreate,
    session: AsyncSession = Depends(get_session),
):
    from app.models import KnowledgeBase
    kb = KnowledgeBase(
        tenant_id=current_tenant_id(),
        **kb_in.model_dump(),
    )
    session.add(kb)
    await session.commit()
    await session.refresh(kb)
    return kb


@router.get("", response_model=list[KnowledgeBaseRead])
async def list_knowledge_bases(
    session: AsyncSession = Depends(get_session),
    skip: int = 0,
    limit: int = 20,
):
    from app.models import KnowledgeBase
    from sqlalchemy import select
    tenant_id = current_tenant_id()
    stmt = select(KnowledgeBase).where(KnowledgeBase.tenant_id == tenant_id).offset(skip).limit(limit)
    result = await session.execute(stmt)
    return result.scalars().all()


@router.get("/{kb_id}", response_model=KnowledgeBaseRead)
async def get_knowledge_base(kb_id: UUID, session: AsyncSession = Depends(get_session)):
    from app.models import KnowledgeBase
    kb = await session.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return kb


@router.patch("/{kb_id}", response_model=KnowledgeBaseRead)
async def update_knowledge_base(
    kb_id: UUID, kb_in: KnowledgeBaseUpdate, session: AsyncSession = Depends(get_session)
):
    from app.models import KnowledgeBase
    kb = await session.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    for field, value in kb_in.model_dump(exclude_unset=True).items():
        setattr(kb, field, value)
    await session.commit()
    await session.refresh(kb)
    return kb


@router.delete("/{kb_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge_base(kb_id: UUID, session: AsyncSession = Depends(get_session)):
    from app.models import KnowledgeBase
    kb = await session.get(KnowledgeBase, kb_id)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    await session.delete(kb)
    await session.commit()


# Document Management
doc_router = APIRouter(prefix="/documents", tags=["Documents"])


@doc_router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def create_document(
    doc_in: DocumentCreate,
    session: AsyncSession = Depends(get_session),
):
    from sqlalchemy import select

    from app.models import Document, KnowledgeBase
    # Verify KB exists
    kb = await session.get(KnowledgeBase, doc_in.knowledge_base_id)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    tenant_id = current_tenant_id()
    # 同一租户下 file_hash 唯一：重复登记返回 409，不要把 IntegrityError 漏成 500
    existing = await session.execute(
        select(Document).where(Document.tenant_id == tenant_id, Document.file_hash == doc_in.file_hash)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Document with this hash already exists")

    doc = Document(
        tenant_id=tenant_id,
        **doc_in.model_dump(),
    )
    session.add(doc)
    await session.commit()
    await session.refresh(doc)
    return doc


@doc_router.post("/ingest", response_model=IngestResponse, status_code=status.HTTP_201_CREATED)
async def ingest_document(req: IngestRequest, session: AsyncSession = Depends(get_session)):
    """一站式入库：登记文档 → 用 metadata.text 分块 → 嵌入 → 刷新 BM25 索引。

    调用方（document-service 解析完成后、或前端上传完）不必再手工调 /documents + /process。
    同一租户下 file_hash 重复时复用已有记录，正文变化才重新分块/嵌入。
    """
    import hashlib
    import time

    from sqlalchemy import select

    from app.models import Document, KnowledgeBase

    start = time.perf_counter()
    kb = await session.get(KnowledgeBase, req.knowledge_base_id)
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    tenant_id = current_tenant_id()
    file_hash = req.file_hash or hashlib.sha256(req.text.encode("utf-8")).hexdigest()

    existing = (
        await session.execute(
            select(Document).where(Document.tenant_id == tenant_id, Document.file_hash == file_hash)
        )
    ).scalar_one_or_none()

    reused = False
    text_changed = True
    if existing is not None:
        reused = True
        previous_text = (existing.meta or {}).get("text")
        text_changed = previous_text != req.text
        doc = existing
        if text_changed:
            doc.meta = {**(existing.meta or {}), **(req.metadata or {}), "text": req.text}
            await session.commit()
    else:
        doc = Document(
            knowledge_base_id=kb.id,
            tenant_id=tenant_id,
            filename=req.title,
            original_filename=req.title,
            content_type="text/plain",
            file_size=len(req.text.encode("utf-8")),
            file_hash=file_hash,
            meta={**(req.metadata or {}), "text": req.text},
        )
        session.add(doc)
        await session.commit()
        await session.refresh(doc)

    force = bool(req.force_reprocess) or (reused and text_changed)
    try:
        result = await doc_processor.process_document(doc.id, force_reprocess=force)
    except EmbeddingUnavailable as exc:
        raise HTTPException(status_code=503, detail=exc.public_message())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc))

    return IngestResponse(
        document_id=doc.id,
        knowledge_base_id=kb.id,
        status=result["status"],
        chunks_created=result.get("chunks_created", 0),
        processing_time_ms=(time.perf_counter() - start) * 1000,
        reused_existing=reused,
    )


@doc_router.get("", response_model=list[DocumentRead])
async def list_documents(
    kb_id: UUID,
    session: AsyncSession = Depends(get_session),
    skip: int = 0,
    limit: int = 20,
):
    from app.models import Document
    from sqlalchemy import select
    tenant_id = current_tenant_id()
    stmt = (
        select(Document)
        .where(Document.knowledge_base_id == kb_id, Document.tenant_id == tenant_id)
        .offset(skip)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


@doc_router.get("/{doc_id}", response_model=DocumentRead)
async def get_document(doc_id: UUID, session: AsyncSession = Depends(get_session)):
    from app.models import Document
    doc = await session.get(Document, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@doc_router.post("/{doc_id}/process", response_model=ProcessDocumentResponse)
async def process_document(doc_id: UUID, req: Optional[ProcessDocumentRequest] = None):
    """分块 + 嵌入 + 写入 document_chunks。body 可省略，默认 force_reprocess=false。"""
    import time
    start = time.perf_counter()
    force_reprocess = bool(req.force_reprocess) if req else False
    try:
        result = await doc_processor.process_document(doc_id, force_reprocess)
        return ProcessDocumentResponse(
            document_id=doc_id,
            status=result["status"],
            chunks_created=result.get("chunks_created", 0),
            processing_time_ms=(time.perf_counter() - start) * 1000,
        )
    except EmbeddingUnavailable as e:
        # 依赖不可用 → 503（调用方可重试），不再是 500
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=e.public_message())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@doc_router.get("/{doc_id}/chunks", response_model=list[DocumentChunkRead])
async def list_document_chunks(
    doc_id: UUID,
    session: AsyncSession = Depends(get_session),
    skip: int = 0,
    limit: int = 50,
):
    from app.models import DocumentChunk
    from sqlalchemy import select
    stmt = (
        select(DocumentChunk)
        .where(DocumentChunk.document_id == doc_id)
        .order_by(DocumentChunk.chunk_index)
        .offset(skip)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


# Retrieval
retrieval_router = APIRouter(prefix="/retrieval", tags=["Retrieval"])


@retrieval_router.post("/search", response_model=RetrievalResponse)
async def search(req: RetrievalRequest):
    tenant_id = current_tenant_id()

    try:
        result = await retrieval_service.retrieve(
            query=req.query,
            kb_id=req.knowledge_base_id,
            tenant_id=tenant_id,
            top_k=req.top_k,
            use_rerank=req.use_rerank,
            filters=req.filters,
        )

        chunks = [
            RetrievedChunk(
                chunk_id=c["chunk_id"],
                document_id=c["document_id"],
                document_filename=c["document_filename"],
                content=c["content"],
                score=c["score"],
                metadata=c["metadata"],
            )
            for c in result["chunks"]
        ]

        if result.get("degraded") and not chunks:
            # embedding 挂了、关键词分支也没命中：对外明确 503，不要返回空结果假装成功
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=result.get("degraded_reason") or "Embedding 服务不可用，且关键词检索无结果",
            )

        return RetrievalResponse(
            query=req.query,
            chunks=chunks,
            total_found=result["total_found"],
            retrieval_time_ms=result["retrieval_time_ms"],
            rerank_time_ms=result["rerank_time_ms"],
            degraded=bool(result.get("degraded")),
            degraded_reason=result.get("degraded_reason"),
        )
    except HTTPException:
        raise
    except EmbeddingUnavailable as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=e.public_message())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Embedding
embedding_router = APIRouter(prefix="/embeddings", tags=["Embeddings"])


@embedding_router.post("", response_model=EmbeddingResponse)
async def create_embeddings(req: EmbeddingRequest):
    from openai import AsyncOpenAI

    model = req.model or settings.EMBEDDING_MODEL

    try:
        # 构造也放进 try：缺 key 时 SDK 在构造阶段就抛错，映射成 503 而不是 500
        client = AsyncOpenAI(
            api_key=settings.EMBEDDING_API_KEY,
            base_url=settings.EMBEDDING_API_BASE,
        )
        response = await client.embeddings.create(
            model=model,
            input=req.texts,
            dimensions=settings.EMBEDDING_DIM if "3-" in model else None,
        )
        return EmbeddingResponse(
            embeddings=[e.embedding for e in response.data],
            model=model,
            usage=response.usage.model_dump() if response.usage else {},
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=EmbeddingUnavailable(
                f"{type(e).__name__}: {str(e)[:200]}", model=model
            ).public_message(),
        )