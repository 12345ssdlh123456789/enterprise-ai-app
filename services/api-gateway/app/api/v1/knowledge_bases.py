# API Gateway - Knowledge Bases Routes

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import get_current_user, get_current_tenant, get_role_permissions, has_permission
from app.db.session import get_async_db
from app.models import KnowledgeBase, User, Document, Tenant
from app.schemas import (
    KnowledgeBaseCreate,
    KnowledgeBaseUpdate,
    KnowledgeBaseResponse,
    KnowledgeBaseListItem,
    RetrievalConfigSchema,
    PaginationParams,
    PaginatedResponse,
    ApiResponse,
    ResponseMeta,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge-bases", tags=["Knowledge Bases"])


def create_meta(request: Request) -> ResponseMeta:
    return ResponseMeta(
        request_id=getattr(request.state, "request_id", "unknown"),
        timestamp=datetime.now(timezone.utc),
        version=settings.APP_VERSION,
    )


def kb_to_list_item(kb: KnowledgeBase) -> KnowledgeBaseListItem:
    return KnowledgeBaseListItem(
        id=kb.id,
        name=kb.name,
        description=kb.description,
        visibility=kb.visibility.value,
        document_count=kb.document_count,
        chunk_count=kb.chunk_count,
        created_at=kb.created_at,
    )


def kb_to_response(kb: KnowledgeBase) -> KnowledgeBaseResponse:
    return KnowledgeBaseResponse(
        id=kb.id,
        tenant_id=kb.tenant_id,
        name=kb.name,
        description=kb.description,
        visibility=kb.visibility.value,
        embedding_model=kb.embedding_model,
        chunk_size=kb.chunk_size,
        chunk_overlap=kb.chunk_overlap,
        retrieval_config=RetrievalConfigSchema(**kb.retrieval_config),
        document_count=kb.document_count,
        chunk_count=kb.chunk_count,
        token_count=kb.token_count,
        created_by=kb.created_by,
        created_at=kb.created_at,
        updated_at=kb.updated_at,
    )


async def _proxied_kb_stats(current_user: User, kb_ids: list) -> dict:
    """转发模式下向 document-service 要真实计数。

    打开 `GATEWAY_PROXY_DOCUMENTS` 后，文档写在 document-service 的库里，网关自己那张
    `documents` 表永远是旧的（`document_count` 恒为 0），知识库页就会「看着有库、里面没文档」。
    这里走后端内部接口拿到真实统计，前端不用改。

    失败时**不报错**，回退到网关本地计数并打 warning：知识库属于网关本体，
    微服务挂了不应该连带知识库页一起 500。
    """
    if not settings.GATEWAY_PROXY_DOCUMENTS or not kb_ids:
        return {}

    path = "/api/v1/internal/kb-stats"
    try:
        from app.core.internal_auth import internal_headers

        headers = internal_headers(
            "POST", path, str(current_user.tenant_id), str(current_user.id)
        )
        headers["Content-Type"] = "application/json"
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                settings.DOCUMENT_SERVICE_URL.rstrip("/") + path,
                json={"knowledge_base_ids": [str(kb_id) for kb_id in kb_ids]},
                headers=headers,
            )
        if resp.status_code != 200:
            logger.warning(
                "知识库统计转发失败（HTTP %s），回退网关本地计数：%s",
                resp.status_code,
                resp.text[:200],
            )
            return {}
        data = resp.json()
        return data if isinstance(data, dict) else {}
    except Exception as exc:  # noqa: BLE001 - 统计是锦上添花，不能拖垮知识库页
        logger.warning("知识库统计转发失败，回退网关本地计数：%s", exc)
        return {}


def _apply_kb_stats(item, stats: dict):
    """用微服务计数覆盖单个知识库响应/列表项里的统计字段。"""
    entry = stats.get(str(item.id))
    if not entry:
        return item
    updates = {}
    for field in ("document_count", "chunk_count", "token_count"):
        if field in entry:
            updates[field] = entry[field]
    return item.model_copy(update=updates) if updates else item


# ============================================
# 获取知识库列表
# ============================================

@router.get("", response_model=ApiResponse[PaginatedResponse[KnowledgeBaseListItem]])
async def list_knowledge_bases(
    request: Request,
    pagination: PaginationParams = Depends(),
    search: Optional[str] = Query(None, description="搜索名称、描述"),
    visibility: Optional[str] = Query(None, description="按可见性筛选"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """获取知识库列表"""
    user_perms = get_role_permissions(current_user.role.value)
    if not has_permission(user_perms, "knowledge-base:read"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: knowledge-base:read",
        )

    # 构建查询
    query = select(KnowledgeBase).where(
        KnowledgeBase.tenant_id == current_tenant.id,
        KnowledgeBase.deleted_at.is_(None),
    )
    count_query = select(func.count(KnowledgeBase.id)).where(
        KnowledgeBase.tenant_id == current_tenant.id,
        KnowledgeBase.deleted_at.is_(None),
    )

    # 可见性过滤：非管理员只能看到 PRIVATE(自己创建) 和 TENANT/PUBLIC
    if current_user.role.value not in ["SUPER_ADMIN", "ADMIN"]:
        query = query.where(
            or_(
                KnowledgeBase.visibility.in_(["TENANT", "PUBLIC"]),
                KnowledgeBase.created_by == current_user.id,
            )
        )
        count_query = count_query.where(
            or_(
                KnowledgeBase.visibility.in_(["TENANT", "PUBLIC"]),
                KnowledgeBase.created_by == current_user.id,
            )
        )

    if search:
        search_term = f"%{search}%"
        query = query.where(
            or_(
                KnowledgeBase.name.ilike(search_term),
                KnowledgeBase.description.ilike(search_term),
            )
        )
        count_query = count_query.where(
            or_(
                KnowledgeBase.name.ilike(search_term),
                KnowledgeBase.description.ilike(search_term),
            )
        )

    if visibility:
        query = query.where(KnowledgeBase.visibility == visibility)
        count_query = count_query.where(KnowledgeBase.visibility == visibility)

    query = query.order_by(KnowledgeBase.created_at.desc())
    offset = (pagination.page - 1) * pagination.page_size
    query = query.offset(offset).limit(pagination.page_size)

    result = await db.execute(query)
    kbs = result.scalars().all()

    count_result = await db.execute(count_query)
    total = count_result.scalar()

    items = [kb_to_list_item(kb) for kb in kbs]
    stats = await _proxied_kb_stats(current_user, [kb.id for kb in kbs])
    if stats:
        items = [_apply_kb_stats(item, stats) for item in items]
    paginated = PaginatedResponse.create(items, total, pagination)

    return ApiResponse(data=paginated, meta=create_meta(request))


# ============================================
# 创建知识库
# ============================================

@router.post("", response_model=ApiResponse[KnowledgeBaseResponse], status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(
    request: Request,
    kb_data: KnowledgeBaseCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """创建知识库"""
    user_perms = get_role_permissions(current_user.role.value)
    if not has_permission(user_perms, "knowledge-base:create"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: knowledge-base:create",
        )

    # 检查租户限制
    kb_count_result = await db.execute(
        select(func.count(KnowledgeBase.id)).where(
            KnowledgeBase.tenant_id == current_tenant.id,
            KnowledgeBase.deleted_at.is_(None),
        )
    )
    kb_count = kb_count_result.scalar()
    max_kbs = current_tenant.settings.get("maxKnowledgeBases", 10)
    if max_kbs > 0 and kb_count >= max_kbs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Knowledge base limit reached ({max_kbs})",
        )

    kb = KnowledgeBase(
        tenant_id=current_tenant.id,
        name=kb_data.name,
        description=kb_data.description,
        visibility=kb_data.visibility,
        embedding_model=kb_data.embedding_model,
        chunk_size=kb_data.chunk_size,
        chunk_overlap=kb_data.chunk_overlap,
        retrieval_config=kb_data.retrieval_config.model_dump(),
        created_by=current_user.id,
    )
    db.add(kb)
    await db.commit()
    await db.refresh(kb)

    return ApiResponse(data=kb_to_response(kb), meta=create_meta(request))


# ============================================
# 获取单个知识库
# ============================================

@router.get("/{kb_id}", response_model=ApiResponse[KnowledgeBaseResponse])
async def get_knowledge_base(
    request: Request,
    kb_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """获取知识库详情"""
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.tenant_id == current_tenant.id,
            KnowledgeBase.deleted_at.is_(None),
        )
    )
    kb = result.scalar_one_or_none()

    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge base not found",
        )

    # 权限检查
    user_perms = get_role_permissions(current_user.role.value)
    if kb.visibility.value == "PRIVATE" and kb.created_by != current_user.id:
        if not has_permission(user_perms, "knowledge-base:read"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied: knowledge-base is private",
            )

    data = kb_to_response(kb)
    stats = await _proxied_kb_stats(current_user, [kb.id])
    if stats:
        data = _apply_kb_stats(data, stats)

    return ApiResponse(data=data, meta=create_meta(request))


# ============================================
# 更新知识库
# ============================================

@router.patch("/{kb_id}", response_model=ApiResponse[KnowledgeBaseResponse])
async def update_knowledge_base(
    request: Request,
    kb_id: UUID,
    kb_data: KnowledgeBaseUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """更新知识库"""
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.tenant_id == current_tenant.id,
            KnowledgeBase.deleted_at.is_(None),
        )
    )
    kb = result.scalar_one_or_none()

    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge base not found",
        )

    # 权限检查：创建者或管理员
    user_perms = get_role_permissions(current_user.role.value)
    if kb.created_by != current_user.id and not has_permission(user_perms, "knowledge-base:update"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: not owner or admin",
        )

    update_data = kb_data.model_dump(exclude_unset=True)

    if "retrieval_config" in update_data and update_data["retrieval_config"]:
        retrieval_config = update_data["retrieval_config"]
        if hasattr(retrieval_config, "model_dump"):
            retrieval_config = retrieval_config.model_dump()
        update_data["retrieval_config"] = retrieval_config

    for field, value in update_data.items():
        setattr(kb, field, value)

    await db.commit()
    await db.refresh(kb)

    return ApiResponse(data=kb_to_response(kb), meta=create_meta(request))


# ============================================
# 删除知识库
# ============================================

@router.delete("/{kb_id}", response_model=ApiResponse)
async def delete_knowledge_base(
    request: Request,
    kb_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """删除知识库 (软删除)"""
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.tenant_id == current_tenant.id,
            KnowledgeBase.deleted_at.is_(None),
        )
    )
    kb = result.scalar_one_or_none()

    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge base not found",
        )

    user_perms = get_role_permissions(current_user.role.value)
    if kb.created_by != current_user.id and not has_permission(user_perms, "knowledge-base:delete"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: not owner or admin",
        )

    from datetime import datetime, timezone
    kb.deleted_at = datetime.now(timezone.utc)

    # 级联软删除文档
    doc_result = await db.execute(
        select(Document).where(
            Document.knowledge_base_id == kb_id,
            Document.deleted_at.is_(None),
        )
    )
    for doc in doc_result.scalars().all():
        doc.deleted_at = datetime.now(timezone.utc)

    await db.commit()

    return ApiResponse(data={"message": "Knowledge base deleted successfully"}, meta=create_meta(request))


# ============================================
# 获取知识库统计
# ============================================

@router.get("/{kb_id}/stats", response_model=ApiResponse)
async def get_knowledge_base_stats(
    request: Request,
    kb_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """获取知识库统计信息"""
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.tenant_id == current_tenant.id,
            KnowledgeBase.deleted_at.is_(None),
        )
    )
    kb = result.scalar_one_or_none()

    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge base not found",
        )

    # 文档状态统计
    from app.models import DocumentStatus
    doc_stats = {}
    # 循环变量不能叫 status：会遮蔽 fastapi 的 status 并让上面的 404 变成 UnboundLocalError
    for doc_status in DocumentStatus:
        count_result = await db.execute(
            select(func.count(Document.id)).where(
                Document.knowledge_base_id == kb_id,
                Document.status == doc_status,
            )
        )
        doc_stats[doc_status.value] = count_result.scalar()

    # 最近文档
    recent_docs_result = await db.execute(
        select(Document).where(
            Document.knowledge_base_id == kb_id,
            Document.deleted_at.is_(None),
        ).order_by(Document.created_at.desc()).limit(5)
    )
    recent_docs = recent_docs_result.scalars().all()

    data = {
        "knowledge_base_id": str(kb_id),
        "document_count": kb.document_count,
        "chunk_count": kb.chunk_count,
        "token_count": kb.token_count,
        "documents_by_status": doc_stats,
        "recent_documents": [
            {"id": str(d.id), "title": d.title, "status": d.status.value, "created_at": d.created_at.isoformat()}
            for d in recent_docs
        ],
    }

    # 转发模式下用 document-service 的真实统计覆盖（否则永远是网关旧库的 0）
    stats = await _proxied_kb_stats(current_user, [kb_id])
    entry = stats.get(str(kb_id))
    if entry:
        for field in ("document_count", "chunk_count", "token_count"):
            if field in entry:
                data[field] = entry[field]
        data["documents_by_status"] = entry.get("documents_by_status", data["documents_by_status"])
        data["recent_documents"] = entry.get("recent_documents", data["recent_documents"])

    return ApiResponse(data=data, meta=create_meta(request))
