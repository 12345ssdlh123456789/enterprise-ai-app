# API Gateway - Documents Routes

import json
import os
import uuid as uuid_lib
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status, Query, UploadFile, File, Form
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import get_current_user, get_current_tenant, get_role_permissions, has_permission
from app.db.session import get_async_db
from app.models import Document, KnowledgeBase, DocumentChunk, DocumentStatus, DocumentType, User, Tenant, NotificationType
from app.services.ingest import ingest_document
from app.services.notify import notify
from app.schemas import (
    DocumentCreate,
    DocumentUpdate,
    DocumentResponse,
    DocumentListItem,
    DocumentChunkSchema,
    PaginationParams,
    PaginatedResponse,
    ApiResponse,
    ResponseMeta,
    FileUploadResponse,
)

router = APIRouter(prefix="/documents", tags=["Documents"])


async def _notify_processed(doc: Document, prefix: str = "") -> None:
    """把解析结果写成一条站内通知（解析完成/失败都能在通知中心看到）。"""
    if doc.status == DocumentStatus.COMPLETED:
        await notify(
            tenant_id=doc.tenant_id,
            user_id=doc.created_by,
            type=NotificationType.SUCCESS,
            title=f"《{doc.title}》{prefix}解析完成",
            content=(
                f"已生成 {doc.chunk_count} 个分块（{doc.token_count} tokens），"
                "可以在知识库里检索了。"
            ),
            data={
                "document_id": str(doc.id),
                "knowledge_base_id": str(doc.knowledge_base_id),
                "event": "document.processed",
            },
        )
    elif doc.status == DocumentStatus.FAILED:
        await notify(
            tenant_id=doc.tenant_id,
            user_id=doc.created_by,
            type=NotificationType.WARNING,
            title=f"《{doc.title}》{prefix}解析失败",
            content=doc.error_message or "解析过程中出现未知错误，可在文档详情里重新解析。",
            data={
                "document_id": str(doc.id),
                "knowledge_base_id": str(doc.knowledge_base_id),
                "event": "document.failed",
            },
        )


def create_meta(request: Request) -> ResponseMeta:
    return ResponseMeta(
        request_id=getattr(request.state, "request_id", "unknown"),
        timestamp=datetime.now(timezone.utc),
        version=settings.APP_VERSION,
    )


def doc_to_list_item(doc: Document) -> DocumentListItem:
    return DocumentListItem(
        id=doc.id,
        title=doc.title,
        file_name=doc.file_name,
        type=doc.type.value,
        status=doc.status.value,
        file_size=doc.file_size,
        mime_type=doc.mime_type,
        chunk_count=doc.chunk_count,
        token_count=doc.token_count,
        created_at=doc.created_at,
    )


def doc_to_response(doc: Document) -> DocumentResponse:
    return DocumentResponse(
        id=doc.id,
        knowledge_base_id=doc.knowledge_base_id,
        tenant_id=doc.tenant_id,
        title=doc.title,
        source_url=doc.source_url,
        file_name=doc.file_name,
        file_size=doc.file_size,
        mime_type=doc.mime_type,
        type=doc.type.value,
        status=doc.status.value,
        chunk_count=doc.chunk_count,
        token_count=doc.token_count,
        error_message=doc.error_message,
        metadata=doc.meta,
        created_by=doc.created_by,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        processed_at=doc.processed_at,
    )


# ============================================
# 文件上传
# ============================================

@router.post("/upload", response_model=ApiResponse[FileUploadResponse], status_code=status.HTTP_201_CREATED)
async def upload_document(
    request: Request,
    knowledge_base_id: UUID = Form(...),
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    metadata: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """上传文档文件"""
    user_perms = get_role_permissions(current_user.role.value)
    if not has_permission(user_perms, "document:create"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: document:create",
        )

    # 验证知识库
    kb_result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == knowledge_base_id,
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

    # 检查文档数量限制
    doc_count_result = await db.execute(
        select(func.count(Document.id)).where(
            Document.knowledge_base_id == knowledge_base_id,
            Document.deleted_at.is_(None),
        )
    )
    doc_count = doc_count_result.scalar()
    max_docs = (current_tenant.settings or {}).get("maxDocumentsPerKB", 1000)
    if max_docs > 0 and doc_count >= max_docs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Document limit reached for this knowledge base ({max_docs})",
        )

    # 验证文件类型
    allowed_types = settings.ALLOWED_FILE_TYPES.split(",")
    file_ext = file.filename.split(".")[-1].lower() if "." in file.filename else ""
    if file_ext not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type not allowed. Allowed: {', '.join(allowed_types)}",
        )

    # 验证文件大小
    content = await file.read()
    if len(content) > settings.MAX_FILE_SIZE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Max size: {settings.MAX_FILE_SIZE_MB}MB",
        )

    # 确定文档类型
    type_mapping = {
        "pdf": DocumentType.PDF,
        "docx": DocumentType.DOCX,
        "md": DocumentType.MARKDOWN,
        "markdown": DocumentType.MARKDOWN,
        "html": DocumentType.HTML,
        "htm": DocumentType.HTML,
        "txt": DocumentType.TXT,
        "csv": DocumentType.CSV,
        "json": DocumentType.JSON,
        "pptx": DocumentType.PPTX,
        "xlsx": DocumentType.XLSX,
    }
    doc_type = type_mapping.get(file_ext, DocumentType.TXT)

    # 保存文件到本地/MinIO
    # TODO: 实现 MinIO 上传
    upload_dir = settings.UPLOAD_DIR
    os.makedirs(upload_dir, exist_ok=True)
    file_id = uuid_lib.uuid4()
    file_path = os.path.join(upload_dir, f"{file_id}.{file_ext}")
    with open(file_path, "wb") as f:
        f.write(content)

    # 创建文档记录
    meta: dict = {}
    if metadata:
        try:
            parsed_meta = json.loads(metadata)
            meta = parsed_meta if isinstance(parsed_meta, dict) else {"raw": parsed_meta}
        except (ValueError, TypeError):
            meta = {"raw": metadata}
    meta.update(
        {
            "file_path": file_path,
            "file_ext": file_ext,
            "original_filename": file.filename,
            "content_type": file.content_type,
        }
    )

    doc = Document(
        knowledge_base_id=knowledge_base_id,
        tenant_id=current_tenant.id,
        title=title or file.filename,
        file_name=file.filename,
        file_size=len(content),
        mime_type=file.content_type,
        type=doc_type,
        status=DocumentStatus.PENDING,
        meta=meta,
        created_by=current_user.id,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    # 本地直接解析 + 分块（没有 document-service 时的默认管线）
    try:
        await ingest_document(db, doc, kb)
    except ValueError as exc:
        doc.status = DocumentStatus.FAILED
        doc.error_message = str(exc)
    await db.commit()
    await db.refresh(doc)

    await _notify_processed(doc, prefix="")

    return ApiResponse(
        data=FileUploadResponse(
            file_id=doc.id,
            file_name=doc.file_name,
            file_size=doc.file_size,
            mime_type=doc.mime_type or "",
            url=f"/api/v1/documents/{doc.id}/download",
        ),
        meta=create_meta(request),
    )


# ============================================
# 创建文档 (从 URL/文本)
# ============================================

@router.post("", response_model=ApiResponse[DocumentResponse], status_code=status.HTTP_201_CREATED)
async def create_document(
    request: Request,
    doc_data: DocumentCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """创建文档 (从 URL 或直接文本)"""
    user_perms = get_role_permissions(current_user.role.value)
    if not has_permission(user_perms, "document:create"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: document:create",
        )

    # 验证知识库
    kb_result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == doc_data.knowledge_base_id,
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

    doc = Document(
        knowledge_base_id=doc_data.knowledge_base_id,
        tenant_id=current_tenant.id,
        title=doc_data.title,
        source_url=doc_data.source_url,
        file_name=doc_data.file_name,
        file_size=doc_data.file_size,
        mime_type=doc_data.mime_type,
        type=doc_data.type,
        status=DocumentStatus.PENDING,
        meta=doc_data.metadata or {},
        created_by=current_user.id,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    return ApiResponse(data=doc_to_response(doc), meta=create_meta(request))


# ============================================
# 获取文档列表
# ============================================

@router.get("", response_model=ApiResponse[PaginatedResponse[DocumentListItem]])
async def list_documents(
    request: Request,
    knowledge_base_id: Optional[UUID] = Query(None, description="知识库 ID"),
    pagination: PaginationParams = Depends(),
    search: Optional[str] = Query(None, description="搜索标题、文件名"),
    status: Optional[str] = Query(None, description="按状态筛选"),
    type: Optional[str] = Query(None, description="按类型筛选"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """获取文档列表"""
    user_perms = get_role_permissions(current_user.role.value)
    if not has_permission(user_perms, "document:read"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: document:read",
        )

    query = select(Document).where(
        Document.tenant_id == current_tenant.id,
        Document.deleted_at.is_(None),
    )
    count_query = select(func.count(Document.id)).where(
        Document.tenant_id == current_tenant.id,
        Document.deleted_at.is_(None),
    )

    if knowledge_base_id:
        query = query.where(Document.knowledge_base_id == knowledge_base_id)
        count_query = count_query.where(Document.knowledge_base_id == knowledge_base_id)

    if search:
        search_term = f"%{search}%"
        query = query.where(
            or_(
                Document.title.ilike(search_term),
                Document.file_name.ilike(search_term),
            )
        )
        count_query = count_query.where(
            or_(
                Document.title.ilike(search_term),
                Document.file_name.ilike(search_term),
            )
        )

    if status:
        query = query.where(Document.status == status)
        count_query = count_query.where(Document.status == status)

    if type:
        query = query.where(Document.type == type)
        count_query = count_query.where(Document.type == type)

    query = query.order_by(Document.created_at.desc())
    offset = (pagination.page - 1) * pagination.page_size
    query = query.offset(offset).limit(pagination.page_size)

    result = await db.execute(query)
    docs = result.scalars().all()

    count_result = await db.execute(count_query)
    total = count_result.scalar()

    items = [doc_to_list_item(d) for d in docs]
    paginated = PaginatedResponse.create(items, total, pagination)

    return ApiResponse(data=paginated, meta=create_meta(request))


# ============================================
# 获取单个文档
# ============================================

@router.get("/{doc_id}", response_model=ApiResponse[DocumentResponse])
async def get_document(
    request: Request,
    doc_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """获取文档详情"""
    result = await db.execute(
        select(Document).where(
            Document.id == doc_id,
            Document.tenant_id == current_tenant.id,
            Document.deleted_at.is_(None),
        )
    )
    doc = result.scalar_one_or_none()

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    # 权限检查：检查知识库可见性
    kb_result = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.id == doc.knowledge_base_id)
    )
    kb = kb_result.scalar_one_or_none()

    if kb and kb.visibility.value == "PRIVATE" and kb.created_by != current_user.id:
        user_perms = get_role_permissions(current_user.role.value)
        if not has_permission(user_perms, "document:read"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied: document is in private knowledge base",
            )

    return ApiResponse(data=doc_to_response(doc), meta=create_meta(request))


# ============================================
# 更新文档
# ============================================

@router.patch("/{doc_id}", response_model=ApiResponse[DocumentResponse])
async def update_document(
    request: Request,
    doc_id: UUID,
    doc_data: DocumentUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """更新文档元数据"""
    result = await db.execute(
        select(Document).where(
            Document.id == doc_id,
            Document.tenant_id == current_tenant.id,
            Document.deleted_at.is_(None),
        )
    )
    doc = result.scalar_one_or_none()

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    user_perms = get_role_permissions(current_user.role.value)
    kb_result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == doc.knowledge_base_id))
    kb = kb_result.scalar_one_or_none()

    if kb and kb.created_by != current_user.id and not has_permission(user_perms, "document:update"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: not owner or admin",
        )

    update_data = doc_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(doc, field, value)

    await db.commit()
    await db.refresh(doc)

    return ApiResponse(data=doc_to_response(doc), meta=create_meta(request))


# ============================================
# 删除文档
# ============================================

@router.delete("/{doc_id}", response_model=ApiResponse)
async def delete_document(
    request: Request,
    doc_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """删除文档 (软删除)"""
    result = await db.execute(
        select(Document).where(
            Document.id == doc_id,
            Document.tenant_id == current_tenant.id,
            Document.deleted_at.is_(None),
        )
    )
    doc = result.scalar_one_or_none()

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    user_perms = get_role_permissions(current_user.role.value)
    kb_result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == doc.knowledge_base_id))
    kb = kb_result.scalar_one_or_none()

    if kb and kb.created_by != current_user.id and not has_permission(user_perms, "document:delete"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: not owner or admin",
        )

    from datetime import datetime, timezone
    doc.deleted_at = datetime.now(timezone.utc)
    doc.status = DocumentStatus.DELETED

    # 级联软删除分块
    chunk_result = await db.execute(
        select(DocumentChunk).where(DocumentChunk.document_id == doc_id)
    )
    for chunk in chunk_result.scalars().all():
        # 分块没有 deleted_at，直接删除或标记
        await db.delete(chunk)

    # 清理上传的原始文件，避免留下无主文件
    file_path = (doc.meta or {}).get("file_path")
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except OSError:
            pass

    await db.commit()

    return ApiResponse(data={"message": "Document deleted successfully"}, meta=create_meta(request))


# ============================================
# 获取文档分块
# ============================================

@router.get("/{doc_id}/chunks", response_model=ApiResponse[PaginatedResponse[DocumentChunkSchema]])
async def list_document_chunks(
    request: Request,
    doc_id: UUID,
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """获取文档分块列表"""
    # 验证文档权限
    doc_result = await db.execute(
        select(Document).where(
            Document.id == doc_id,
            Document.tenant_id == current_tenant.id,
            Document.deleted_at.is_(None),
        )
    )
    doc = doc_result.scalar_one_or_none()

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    kb_result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == doc.knowledge_base_id))
    kb = kb_result.scalar_one_or_none()

    if kb and kb.visibility.value == "PRIVATE" and kb.created_by != current_user.id:
        user_perms = get_role_permissions(current_user.role.value)
        if not has_permission(user_perms, "document:read"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied",
            )

    query = select(DocumentChunk).where(DocumentChunk.document_id == doc_id).order_by(DocumentChunk.sequence)
    count_query = select(func.count(DocumentChunk.id)).where(DocumentChunk.document_id == doc_id)

    offset = (pagination.page - 1) * pagination.page_size
    query = query.offset(offset).limit(pagination.page_size)

    result = await db.execute(query)
    chunks = result.scalars().all()

    count_result = await db.execute(count_query)
    total = count_result.scalar()

    items = [
        DocumentChunkSchema(
            id=c.id,
            document_id=c.document_id,
            content=c.content,
            token_count=c.token_count,
            sequence=c.sequence,
            metadata=c.meta,
        )
        for c in chunks
    ]

    paginated = PaginatedResponse.create(items, total, pagination)

    return ApiResponse(data=paginated, meta=create_meta(request))


# ============================================
# 重新处理文档
# ============================================

@router.post("/{doc_id}/reprocess", response_model=ApiResponse)
async def reprocess_document(
    request: Request,
    doc_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """重新处理文档 (触发文档处理管线)"""
    result = await db.execute(
        select(Document).where(
            Document.id == doc_id,
            Document.tenant_id == current_tenant.id,
            Document.deleted_at.is_(None),
        )
    )
    doc = result.scalar_one_or_none()

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    user_perms = get_role_permissions(current_user.role.value)
    kb_result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == doc.knowledge_base_id))
    kb = kb_result.scalar_one_or_none()

    if kb and kb.created_by != current_user.id and not has_permission(user_perms, "document:update"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied",
        )

    # 重置状态
    doc.status = DocumentStatus.PENDING
    doc.error_message = None
    doc.chunk_count = 0
    doc.token_count = 0

    try:
        chunk_count = await ingest_document(db, doc, kb)
        await db.commit()
        await db.refresh(doc)
    except ValueError as exc:
        doc.status = DocumentStatus.FAILED
        doc.error_message = str(exc)
        await db.commit()
        await _notify_processed(doc, prefix="重新")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    await _notify_processed(doc, prefix="重新")

    return ApiResponse(
        data={
            "message": "Document reprocessed",
            "chunk_count": chunk_count,
            "status": doc.status.value,
        },
        meta=create_meta(request),
    )
