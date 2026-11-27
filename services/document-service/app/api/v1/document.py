import logging
from uuid import UUID
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.config import settings
from app.db.session import get_session
from app.schemas import (
    DocumentCreate,
    DocumentUpdate,
    DocumentRead,
    DocumentVersionRead,
    PresignedUploadUrlRequest,
    PresignedUploadUrlResponse,
    PresignedDownloadUrlRequest,
    PresignedDownloadUrlResponse,
    DocumentProcessRequest,
    DocumentProcessResponse,
    BatchUploadRequest,
    BatchUploadResponse,
)
from app.models import Document, DocumentVersion, DocumentStatus, DocumentType
from app.services.document_processor import DocumentProcessor
from app.services.rag_ingest import ingest_document_text
from app.services.storage import get_storage_client, object_key_from_path
from app.core.context import current_tenant_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["Documents"])
upload_router = APIRouter(prefix="/upload", tags=["Upload"])
download_router = APIRouter(prefix="/download", tags=["Download"])
storage_router = APIRouter(prefix="/storage", tags=["Storage"])
# 服务间内部接口（网关用，不对外暴露在文档页面上）
internal_router = APIRouter(prefix="/internal", tags=["Internal"])

doc_processor = DocumentProcessor()
storage = get_storage_client()


_MIME_TO_DOCUMENT_TYPE = {
    "application/pdf": DocumentType.PDF,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DocumentType.DOCX,
    "text/plain": DocumentType.TXT,
    "text/markdown": DocumentType.MARKDOWN,
    "image/png": DocumentType.IMAGE,
    "image/jpeg": DocumentType.IMAGE,
    "image/tiff": DocumentType.IMAGE,
}

_EXT_TO_DOCUMENT_TYPE = {
    "pdf": DocumentType.PDF,
    "docx": DocumentType.DOCX,
    "txt": DocumentType.TXT,
    "md": DocumentType.MARKDOWN,
    "png": DocumentType.IMAGE,
    "jpg": DocumentType.IMAGE,
    "jpeg": DocumentType.IMAGE,
    "tif": DocumentType.IMAGE,
    "tiff": DocumentType.IMAGE,
}


def infer_document_type(content_type: str, filename: str) -> DocumentType:
    """注册文档时补齐 model 必填的 document_type（MIME 优先，其次扩展名）。"""
    mime = (content_type or "").split(";")[0].strip().lower()
    if mime in _MIME_TO_DOCUMENT_TYPE:
        return _MIME_TO_DOCUMENT_TYPE[mime]
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return _EXT_TO_DOCUMENT_TYPE.get(ext, DocumentType.OTHER)


def _revive_deleted_document(doc: Document, fields: dict, *, status: DocumentStatus) -> Document:
    """复活一条软删除的文档记录。

    `documents` 上有 `(tenant_id, file_hash)` 唯一约束，**软删除的记录同样占着它**，
    所以删除后再传同一份内容既不能直接插入（撞约束），也不能把旧记录当“重复”返回
    （它的存储对象已经被删了，后续 process/download 会报“对象不存在”）。
    正确做法就是复用这条记录、清空所有衍生字段，让调用方重新上传/解析。
    """
    for key, value in fields.items():
        if value is not None and hasattr(doc, key):
            setattr(doc, key, value)
    doc.status = status
    doc.error_message = None
    doc.page_count = 0
    doc.chunk_count = 0
    doc.token_count = 0
    doc.processed_at = None
    return doc


# Document CRUD
@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def create_document(
    doc_in: DocumentCreate,
    session: AsyncSession = Depends(get_session),
):
    tenant_id = current_tenant_id()

    # 唯一约束是 (tenant_id, file_hash)，软删除的记录也占着它 → 必须连 DELETED 一起查
    stmt = select(Document).where(
        Document.tenant_id == tenant_id,
        Document.file_hash == doc_in.file_hash,
    )
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing and existing.status != DocumentStatus.DELETED:
        raise HTTPException(status_code=409, detail="Document with this hash already exists")
    if existing:
        _revive_deleted_document(
            existing, doc_in.model_dump(), status=DocumentStatus.UPLOADING
        )
        session.add(existing)
        await session.commit()
        await session.refresh(existing)
        return existing

    doc = Document(
        tenant_id=tenant_id,
        document_type=infer_document_type(doc_in.content_type, doc_in.filename),
        storage_path=f"documents/{tenant_id}/{doc_in.file_hash}",
        **doc_in.model_dump(),
    )
    session.add(doc)
    await session.commit()
    await session.refresh(doc)
    return doc


@router.get("", response_model=List[DocumentRead])
async def list_documents(
    response: Response,
    session: AsyncSession = Depends(get_session),
    knowledge_base_id: Optional[UUID] = None,
    status_filter: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
):
    tenant_id = current_tenant_id()
    # 软删除（status=DELETED）的文档不能再出现在列表里
    stmt = select(Document).where(
        Document.tenant_id == tenant_id, Document.status != DocumentStatus.DELETED
    )
    count_stmt = select(func.count(Document.id)).where(
        Document.tenant_id == tenant_id, Document.status != DocumentStatus.DELETED
    )

    if knowledge_base_id:
        stmt = stmt.where(Document.knowledge_base_id == knowledge_base_id)
        count_stmt = count_stmt.where(Document.knowledge_base_id == knowledge_base_id)
    if status_filter:
        stmt = stmt.where(Document.status == status_filter)
        count_stmt = count_stmt.where(Document.status == status_filter)

    stmt = stmt.order_by(Document.created_at.desc()).offset(skip).limit(limit)
    result = await session.execute(stmt)
    # 总数放响应头：列表体仍是数组（老调用方不受影响），网关转发时用它拼分页信封
    total = (await session.execute(count_stmt)).scalar() or 0
    response.headers["X-Total-Count"] = str(total)
    return result.scalars().all()


@internal_router.post("/kb-stats")
async def knowledge_base_stats(payload: dict, session: AsyncSession = Depends(get_session)):
    """网关的知识库页在转发模式下需要真实计数（网关自己的 documents 表此时是空的）。

    入参 `{"knowledge_base_ids": [...]}`，返回 `{kb_id: {document_count, chunk_count,
    token_count, documents_by_status, recent_documents}}`。只统计**本租户**、未软删除的文档，
    没传/没权限的 id 一律不出现，避免通过统计接口探测别人的知识库。
    """
    from uuid import UUID as _UUID

    raw_ids = payload.get("knowledge_base_ids") or []
    ids: list[_UUID] = []
    for raw in raw_ids:
        try:
            ids.append(_UUID(str(raw)))
        except (TypeError, ValueError):
            continue
    if not ids:
        return {}

    tenant_id = current_tenant_id()
    where = [
        Document.tenant_id == tenant_id,
        Document.status != DocumentStatus.DELETED,
        Document.knowledge_base_id.in_(ids),
    ]

    # 每个 KB 的总数 / 分块数 / token 数
    totals_stmt = (
        select(
            Document.knowledge_base_id,
            func.count(Document.id),
            func.coalesce(func.sum(Document.chunk_count), 0),
            func.coalesce(func.sum(Document.token_count), 0),
        )
        .where(*where)
        .group_by(Document.knowledge_base_id)
    )
    totals = (await session.execute(totals_stmt)).all()

    # 按状态分组
    status_stmt = (
        select(Document.knowledge_base_id, Document.status, func.count(Document.id))
        .where(*where)
        .group_by(Document.knowledge_base_id, Document.status)
    )
    status_rows = (await session.execute(status_stmt)).all()

    # 每个 KB 最近 5 篇（一次查询后在 Python 里截断，避免 N+1）
    recent_stmt = (
        select(Document.knowledge_base_id, Document.id, Document.filename, Document.status, Document.created_at)
        .where(*where)
        .order_by(Document.created_at.desc())
        .limit(5 * len(ids))
    )
    recent_rows = (await session.execute(recent_stmt)).all()

    stats: dict[str, dict] = {
        str(kb_id): {
            "document_count": 0,
            "chunk_count": 0,
            "token_count": 0,
            "documents_by_status": {s.value: 0 for s in DocumentStatus},
            "recent_documents": [],
        }
        for kb_id in ids
    }
    for kb_id, doc_count, chunk_count, token_count in totals:
        entry = stats[str(kb_id)]
        entry["document_count"] = int(doc_count)
        entry["chunk_count"] = int(chunk_count)
        entry["token_count"] = int(token_count)
    for kb_id, doc_status, doc_count in status_rows:
        stats[str(kb_id)]["documents_by_status"][doc_status.value] = int(doc_count)
    for kb_id, doc_id, title, doc_status, created_at in recent_rows:
        entry = stats[str(kb_id)]
        if len(entry["recent_documents"]) >= 5:
            continue
        entry["recent_documents"].append(
            {
                "id": str(doc_id),
                # 微服务没有 title 字段，网关的这个字段一直就是文件名
                "title": title,
                "status": doc_status.value,
                "created_at": created_at.isoformat(),
            }
        )
    return stats


async def _get_tenant_document(session: AsyncSession, doc_id: UUID) -> Document:
    """按租户取文档：ID 猜对了也不能跨租户读写（否则 UUID 泄露就等于授权）。"""
    stmt = select(Document).where(
        Document.id == doc_id,
        Document.tenant_id == current_tenant_id(),
    )
    doc = (await session.execute(stmt)).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.get("/{doc_id}", response_model=DocumentRead)
async def get_document(doc_id: UUID, session: AsyncSession = Depends(get_session)):
    return await _get_tenant_document(session, doc_id)


@router.patch("/{doc_id}", response_model=DocumentRead)
async def update_document(
    doc_id: UUID,
    doc_in: DocumentUpdate,
    session: AsyncSession = Depends(get_session),
):
    doc = await _get_tenant_document(session, doc_id)

    for field, value in doc_in.model_dump(exclude_unset=True).items():
        setattr(doc, field, value)
    await session.commit()
    await session.refresh(doc)
    return doc


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(doc_id: UUID, session: AsyncSession = Depends(get_session)):
    doc = await _get_tenant_document(session, doc_id)

    # Delete from MinIO
    try:
        object_key = object_key_from_path(doc.storage_path)
        storage.delete(object_key)
    except Exception:
        pass  # Log but don't fail

    doc.status = DocumentStatus.DELETED
    await session.commit()


@router.get("/{doc_id}/versions", response_model=List[DocumentVersionRead])
async def list_document_versions(
    doc_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    await _get_tenant_document(session, doc_id)

    stmt = select(DocumentVersion).where(DocumentVersion.document_id == doc_id).order_by(DocumentVersion.version_number.desc())
    result = await session.execute(stmt)
    return result.scalars().all()


async def _parse_and_ingest(doc: Document, session: AsyncSession) -> tuple[dict, dict | None]:
    """解析文档并把正文送进 rag-service。

    `/process` 与预签名 `/upload/complete` 共用这一段，避免两条上传链路行为不一致。
    ingest 是 best-effort（rag 未起/无知识库时返回 None），不会让解析失败。
    """
    result = await doc_processor.process_document(doc)
    await session.commit()

    ingest = await ingest_document_text(
        tenant_id=doc.tenant_id,
        user_id=doc.created_by,
        knowledge_base_id=doc.knowledge_base_id,
        title=doc.original_filename or doc.filename,
        text=(doc.meta or {}).get("text") or "",
        file_hash=doc.file_hash,
    )
    return result, ingest


# Upload - Presigned URLs
@upload_router.post("/presigned-url", response_model=PresignedUploadUrlResponse)
async def get_presigned_upload_url(
    req: PresignedUploadUrlRequest,
):
    """Get presigned URL for direct upload to MinIO."""
    tenant_id = current_tenant_id()

    # Generate object key
    ext = req.filename.split(".")[-1] if "." in req.filename else "bin"
    file_hash = req.file_hash
    object_key = f"{tenant_id}/{file_hash[:2]}/{file_hash}.{ext}"

    upload_url = storage.presigned_upload_url(object_key, expires_in=3600)

    return PresignedUploadUrlResponse(
        upload_url=upload_url,
        object_key=object_key,
        expires_in=3600,
    )


@upload_router.post("/presigned-urls/batch", response_model=BatchUploadResponse)
async def get_batch_presigned_upload_urls(
    req: BatchUploadRequest,
):
    """Get multiple presigned URLs for batch upload."""
    results = []
    for file_req in req.files:
        result = await get_presigned_upload_url(file_req)
        results.append(result)
    return BatchUploadResponse(upload_urls=results)


@upload_router.post("/complete")
async def complete_upload(
    object_key: str = Form(...),
    filename: str = Form(...),
    content_type: str = Form(...),
    file_size: int = Form(...),
    file_hash: str = Form(...),
    knowledge_base_id: Optional[UUID] = Form(None),
    session: AsyncSession = Depends(get_session),
):
    """Complete upload after client uploads to MinIO."""
    tenant_id = current_tenant_id()

    # Verify file exists in MinIO
    try:
        storage.download(object_key)
    except Exception:
        raise HTTPException(status_code=400, detail="File not found in storage")

    # 唯一约束含软删除记录：只把「未删除」当重复，删除过的走复活
    stmt = select(Document).where(
        Document.tenant_id == tenant_id,
        Document.file_hash == file_hash,
    )
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing and existing.status != DocumentStatus.DELETED:
        return {"document_id": str(existing.id), "status": "duplicate"}

    doc_type = infer_document_type(content_type, filename)
    storage_path = storage.describe_path(object_key)
    fields = {
        "knowledge_base_id": knowledge_base_id,
        "filename": filename,
        "original_filename": filename,
        "content_type": content_type,
        "document_type": doc_type,
        "file_size": file_size,
        "storage_path": storage_path,
    }

    if existing:
        doc = _revive_deleted_document(existing, fields, status=DocumentStatus.UPLOADED)
        session.add(doc)
    else:
        doc = Document(
            tenant_id=tenant_id,
            file_hash=file_hash,
            status=DocumentStatus.UPLOADED,
            **fields,
        )
        session.add(doc)
    await session.commit()
    await session.refresh(doc)

    response = {
        "document_id": str(doc.id),
        "status": "created",
        "document_status": doc.status.value if hasattr(doc.status, "value") else str(doc.status),
        "processed": False,
        "rag_ingested": False,
    }

    # 预签名上传以前到这一步就结束，调用方还得手动调 /process，
    # 因此 AUTO_INGEST_TO_RAG 对这条链路完全不生效。这里解析完顺带入库。
    if settings.AUTO_PROCESS_ON_UPLOAD:
        try:
            result, ingest = await _parse_and_ingest(doc, session)
            response["document_status"] = doc.status.value if hasattr(doc.status, "value") else str(doc.status)
            response["processed"] = result["status"] == "processed"
            response["page_count"] = result["page_count"]
            response["rag_ingested"] = bool(ingest)
        except Exception as exc:  # noqa: BLE001 - 解析失败不应让上传本身失败
            await session.commit()
            logger.warning("auto process after upload complete failed: %s", exc)
            response["document_status"] = doc.status.value if hasattr(doc.status, "value") else str(doc.status)
            response["process_error"] = str(exc)

    return response


@upload_router.post("/multipart", response_model=DocumentRead)
async def upload_multipart(
    file: UploadFile = File(...),
    knowledge_base_id: Optional[UUID] = Form(None),
    session: AsyncSession = Depends(get_session),
):
    """Direct multipart upload (for smaller files)."""
    tenant_id = current_tenant_id()

    # Read file
    file_data = await file.read()
    file_size = len(file_data)

    if file_size > settings.MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large")

    if file.content_type not in settings.allowed_mime_types_list:
        raise HTTPException(status_code=400, detail="File type not allowed")

    file_hash = hashlib.sha256(file_data).hexdigest()

    # 唯一约束含软删除记录：未删除 → 直接返回既有文档；已删除 → 复活（见 _revive_deleted_document）
    stmt = select(Document).where(
        Document.tenant_id == tenant_id,
        Document.file_hash == file_hash,
    )
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing and existing.status != DocumentStatus.DELETED:
        return existing

    # Upload to MinIO
    object_key = f"{tenant_id}/{file_hash[:2]}/{file_hash}.{file.filename.split('.')[-1] if '.' in file.filename else 'bin'}"
    storage_path = storage.upload(object_key, file_data, file.content_type)

    fields = {
        "knowledge_base_id": knowledge_base_id,
        "filename": file.filename,
        "original_filename": file.filename,
        "content_type": file.content_type,
        "document_type": infer_document_type(file.content_type, file.filename),
        "file_size": file_size,
        "storage_path": storage_path,
    }
    if existing:
        doc = _revive_deleted_document(existing, fields, status=DocumentStatus.UPLOADED)
        session.add(doc)
    else:
        doc = Document(
            tenant_id=tenant_id,
            file_hash=file_hash,
            status=DocumentStatus.UPLOADED,
            **fields,
        )
        session.add(doc)
    await session.commit()
    await session.refresh(doc)

    return doc


# Download
@download_router.post("/presigned-url", response_model=PresignedDownloadUrlResponse)
async def get_presigned_download_url(
    req: PresignedDownloadUrlRequest,
):
    """Get presigned URL for download."""
    download_url = storage.presigned_download_url(req.object_key, req.expires_in)
    return PresignedDownloadUrlResponse(download_url=download_url, expires_in=req.expires_in)


@download_router.get("/{doc_id}")
async def download_document(doc_id: UUID, session: AsyncSession = Depends(get_session)):
    """Download document directly."""
    doc = await _get_tenant_document(session, doc_id)

    try:
        object_key = object_key_from_path(doc.storage_path)
        file_data = storage.download(object_key)
        return StreamingResponse(
            io.BytesIO(file_data),
            media_type=doc.content_type,
            headers={"Content-Disposition": f'attachment; filename="{doc.original_filename}"'},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")


# Processing
@router.post("/{doc_id}/process", response_model=DocumentProcessResponse)
async def process_document(
    doc_id: UUID,
    req: Optional[DocumentProcessRequest] = None,
    session: AsyncSession = Depends(get_session),
):
    """Process document (parse, extract text). body 可省略，默认 force_reprocess=false。"""
    force_reprocess = bool(req.force_reprocess) if req else False

    doc = await _get_tenant_document(session, doc_id)

    if doc.status == DocumentStatus.PROCESSED and not force_reprocess:
        return DocumentProcessResponse(
            document_id=doc_id,
            status="already_processed",
            page_count=doc.page_count,
            chunk_count=doc.chunk_count,
            token_count=doc.token_count,
            processing_time_ms=0,
        )

    try:
        # 解析完成后直接把正文送进 rag-service（失败不影响本次解析，只记日志）
        result, ingest = await _parse_and_ingest(doc, session)

        return DocumentProcessResponse(
            document_id=doc_id,
            status=result["status"],
            page_count=result["page_count"],
            chunk_count=doc.chunk_count,
            token_count=doc.token_count,
            processing_time_ms=result["processing_time_ms"],
            rag_ingested=bool(ingest),
        )
    except Exception as e:
        doc.status = DocumentStatus.FAILED
        doc.error_message = str(e)
        await session.commit()
        raise HTTPException(status_code=500, detail=str(e))


# Stats
@router.get("/stats/summary")
async def get_document_stats(
    session: AsyncSession = Depends(get_session),
):
    tenant_id = current_tenant_id()

    stmt = select(
        func.count(Document.id).label("total"),
        func.sum(Document.file_size).label("total_size"),
        func.sum(Document.page_count).label("total_pages"),
        func.sum(Document.chunk_count).label("total_chunks"),
        func.sum(Document.token_count).label("total_tokens"),
    ).where(Document.tenant_id == tenant_id, Document.status != DocumentStatus.DELETED)

    result = await session.execute(stmt)
    row = result.one()

    # By status
    stmt = select(Document.status, func.count(Document.id)).where(
        Document.tenant_id == tenant_id
    ).group_by(Document.status)
    result = await session.execute(stmt)
    by_status = {str(status): count for status, count in result.all()}

    # By type
    stmt = select(Document.document_type, func.count(Document.id)).where(
        Document.tenant_id == tenant_id
    ).group_by(Document.document_type)
    result = await session.execute(stmt)
    by_type = {str(doc_type): count for doc_type, count in result.all()}

    return {
        "total_documents": row.total or 0,
        "total_size_bytes": row.total_size or 0,
        "total_pages": row.total_pages or 0,
        "total_chunks": row.total_chunks or 0,
        "total_tokens": row.total_tokens or 0,
        "by_status": by_status,
        "by_type": by_type,
    }


import hashlib
import io


# Storage：local provider 的 presigned URL 指向这里，用法与 MinIO 预签名 PUT/GET 一致
@storage_router.put("/{object_key:path}", status_code=status.HTTP_204_NO_CONTENT)
async def put_object(object_key: str, request: Request):
    """接收客户端直传的字节（local 模式下代替 MinIO 的对象写入）。"""
    body = await request.body()
    storage.upload(object_key, body, request.headers.get("content-type", "application/octet-stream"))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@storage_router.get("/{object_key:path}")
async def get_object(object_key: str):
    """读取对象字节（local 模式下代替 MinIO 的预签名 GET）。"""
    try:
        data = storage.download(object_key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Object not found")
    return Response(content=data, media_type="application/octet-stream")

