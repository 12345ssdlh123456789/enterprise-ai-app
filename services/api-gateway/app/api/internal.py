# API Gateway - Internal Routes (Service-to-Service)

from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status, Query, Body
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import verify_service_token
from app.db.session import get_async_db
from app.models import (
    User, Tenant, KnowledgeBase, Document, DocumentChunk,
    Conversation, Message, WorkflowExecution,
    CostRecord, TokenBudget, Model, ModelProvider, DocumentStatus, ExecutionStatus
)
from app.schemas import (
    ApiResponse,
    ResponseMeta,
)

router = APIRouter(prefix="/internal", tags=["Internal"])


def create_meta(request: Request) -> ResponseMeta:
    return ResponseMeta(
        request_id=getattr(request.state, "request_id", "unknown"),
        timestamp=datetime.now(timezone.utc),
        version=settings.APP_VERSION,
    )


# ============================================
# 依赖：验证服务 Token
# ============================================

async def require_service_auth(request: Request):
    """验证服务间调用 Token"""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Service authentication required",
        )

    token = auth_header[7:]
    if not verify_service_token(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid service token",
        )

    return True


# ============================================
# 用户相关
# ============================================

@router.get("/users/{user_id}", response_model=ApiResponse)
async def internal_get_user(
    request: Request,
    user_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    _: bool = Depends(require_service_auth),
):
    """内部服务获取用户信息"""
    result = await db.execute(
        select(User).where(User.id == user_id, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return ApiResponse(data={
        "id": str(user.id),
        "email": user.email,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role.value,
        "status": user.status.value,
        "tenant_id": str(user.tenant_id),
    }, meta=create_meta(request))


@router.get("/users/by-email/{email}", response_model=ApiResponse)
async def internal_get_user_by_email(
    request: Request,
    email: str,
    db: AsyncSession = Depends(get_async_db),
    _: bool = Depends(require_service_auth),
):
    """内部服务通过邮箱获取用户"""
    result = await db.execute(
        select(User).where(User.email == email, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return ApiResponse(data={
        "id": str(user.id),
        "email": user.email,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role.value,
        "status": user.status.value,
        "tenant_id": str(user.tenant_id),
    }, meta=create_meta(request))


# ============================================
# 租户相关
# ============================================

@router.get("/tenants/{tenant_id}", response_model=ApiResponse)
async def internal_get_tenant(
    request: Request,
    tenant_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    _: bool = Depends(require_service_auth),
):
    """内部服务获取租户信息"""
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )

    return ApiResponse(data={
        "id": str(tenant.id),
        "name": tenant.name,
        "slug": tenant.slug,
        "plan": tenant.plan.value,
        "settings": tenant.settings,
    }, meta=create_meta(request))


# ============================================
# 知识库相关
# ============================================

@router.get("/knowledge-bases/{kb_id}", response_model=ApiResponse)
async def internal_get_knowledge_base(
    request: Request,
    kb_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    _: bool = Depends(require_service_auth),
):
    """内部服务获取知识库信息"""
    result = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.id == kb_id, KnowledgeBase.deleted_at.is_(None))
    )
    kb = result.scalar_one_or_none()

    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge base not found",
        )

    return ApiResponse(data={
        "id": str(kb.id),
        "tenant_id": str(kb.tenant_id),
        "name": kb.name,
        "embedding_model": kb.embedding_model,
        "chunk_size": kb.chunk_size,
        "chunk_overlap": kb.chunk_overlap,
        "retrieval_config": kb.retrieval_config,
    }, meta=create_meta(request))


# ============================================
# 文档相关
# ============================================

@router.get("/documents/{doc_id}", response_model=ApiResponse)
async def internal_get_document(
    request: Request,
    doc_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    _: bool = Depends(require_service_auth),
):
    """内部服务获取文档信息"""
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.deleted_at.is_(None))
    )
    doc = result.scalar_one_or_none()

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    return ApiResponse(data={
        "id": str(doc.id),
        "knowledge_base_id": str(doc.knowledge_base_id),
        "tenant_id": str(doc.tenant_id),
        "title": doc.title,
        "file_name": doc.file_name,
        "file_size": doc.file_size,
        "mime_type": doc.mime_type,
        "type": doc.type.value,
        "status": doc.status.value,
        "metadata": doc.meta,
    }, meta=create_meta(request))


@router.patch("/documents/{doc_id}/status", response_model=ApiResponse)
async def internal_update_document_status(
    request: Request,
    doc_id: UUID,
    status: str = Body(..., embed=True),
    error_message: Optional[str] = Body(None, embed=True),
    chunk_count: Optional[int] = Body(None, embed=True),
    token_count: Optional[int] = Body(None, embed=True),
    db: AsyncSession = Depends(get_async_db),
    _: bool = Depends(require_service_auth),
):
    """内部服务更新文档状态 (document-service 调用)"""
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.deleted_at.is_(None))
    )
    doc = result.scalar_one_or_none()

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    # 验证状态值
    try:
        doc.status = DocumentStatus(status)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status: {status}",
        )

    if error_message is not None:
        doc.error_message = error_message

    if chunk_count is not None:
        doc.chunk_count = chunk_count

    if token_count is not None:
        doc.token_count = token_count

    if doc.status == DocumentStatus.COMPLETED:
        doc.processed_at = datetime.now()

    # 更新知识库统计
    if doc.status == DocumentStatus.COMPLETED:
        kb_result = await db.execute(
            select(KnowledgeBase).where(KnowledgeBase.id == doc.knowledge_base_id)
        )
        kb = kb_result.scalar_one_or_none()
        if kb:
            kb.document_count = await db.scalar(
                select(func.count(Document.id)).where(
                    Document.knowledge_base_id == kb.id,
                    Document.deleted_at.is_(None),
                )
            )
            kb.chunk_count = await db.scalar(
                select(func.count(DocumentChunk.id)).where(
                    DocumentChunk.knowledge_base_id == kb.id,
                )
            )

    await db.commit()

    return ApiResponse(data={"message": "Document status updated"}, meta=create_meta(request))


@router.post("/documents/{doc_id}/chunks", response_model=ApiResponse)
async def internal_create_document_chunks(
    request: Request,
    doc_id: UUID,
    chunks: List[Dict[str, Any]] = Body(...),
    db: AsyncSession = Depends(get_async_db),
    _: bool = Depends(require_service_auth),
):
    """内部服务批量创建文档分块 (document-service 调用)"""
    result = await db.execute(
        select(Document).where(Document.id == doc_id, Document.deleted_at.is_(None))
    )
    doc = result.scalar_one_or_none()

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    # 批量插入分块
    for chunk_data in chunks:
        chunk = DocumentChunk(
            document_id=doc_id,
            knowledge_base_id=doc.knowledge_base_id,
            content=chunk_data["content"],
            token_count=chunk_data["token_count"],
            sequence=chunk_data["sequence"],
            meta=chunk_data.get("metadata", {}),
            embedding=chunk_data.get("embedding"),
        )
        db.add(chunk)

    await db.commit()

    return ApiResponse(data={"message": f"Created {len(chunks)} chunks"}, meta=create_meta(request))


# ============================================
# 对话相关
# ============================================

@router.post("/conversations", response_model=ApiResponse)
async def internal_create_conversation(
    request: Request,
    tenant_id: UUID = Body(...),
    knowledge_base_id: Optional[UUID] = Body(None),
    title: str = Body("新对话"),
    model: str = Body("gpt-4o-mini"),
    created_by: UUID = Body(...),
    db: AsyncSession = Depends(get_async_db),
    _: bool = Depends(require_service_auth),
):
    """内部服务创建对话 (llm-service/rag-service 调用)"""
    conv = Conversation(
        tenant_id=tenant_id,
        knowledge_base_id=knowledge_base_id,
        title=title,
        model=model,
        created_by=created_by,
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)

    return ApiResponse(data={"id": str(conv.id)}, meta=create_meta(request))


@router.post("/messages", response_model=ApiResponse)
async def internal_create_message(
    request: Request,
    conversation_id: UUID = Body(...),
    role: str = Body(...),
    content: str = Body(...),
    token_count: Optional[int] = Body(None),
    model: Optional[str] = Body(None),
    citations: Optional[List[Dict]] = Body(None),
    metadata: Optional[Dict] = Body(None),
    db: AsyncSession = Depends(get_async_db),
    _: bool = Depends(require_service_auth),
):
    """内部服务创建消息"""
    msg = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        token_count=token_count,
        model=model,
        citations=citations,
        meta=metadata or {},
    )
    db.add(msg)

    # 更新对话统计
    conv_result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conv = conv_result.scalar_one_or_none()
    if conv:
        conv.message_count += 1
        if token_count:
            conv.total_tokens += token_count

    await db.commit()

    return ApiResponse(data={"id": str(msg.id)}, meta=create_meta(request))


# ============================================
# 工作流执行相关
# ============================================

@router.post("/workflow-executions", response_model=ApiResponse)
async def internal_create_workflow_execution(
    request: Request,
    workflow_id: UUID = Body(...),
    tenant_id: UUID = Body(...),
    input: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_async_db),
    _: bool = Depends(require_service_auth),
):
    """内部服务创建工作流执行记录"""
    execution = WorkflowExecution(
        workflow_id=workflow_id,
        tenant_id=tenant_id,
        status=ExecutionStatus.PENDING,
        input=input,
    )
    db.add(execution)
    await db.commit()
    await db.refresh(execution)

    return ApiResponse(data={"id": str(execution.id)}, meta=create_meta(request))


@router.patch("/workflow-executions/{execution_id}", response_model=ApiResponse)
async def internal_update_workflow_execution(
    request: Request,
    execution_id: UUID,
    status: Optional[str] = Body(None),
    output: Optional[Dict[str, Any]] = Body(None),
    error: Optional[str] = Body(None),
    node_executions: Optional[List[Dict]] = Body(None),
    db: AsyncSession = Depends(get_async_db),
    _: bool = Depends(require_service_auth),
):
    """内部服务更新工作流执行状态"""
    result = await db.execute(
        select(WorkflowExecution).where(WorkflowExecution.id == execution_id)
    )
    execution = result.scalar_one_or_none()

    if not execution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Execution not found",
        )

    if status:
        execution.status = ExecutionStatus(status)
    if output is not None:
        execution.output = output
    if error is not None:
        execution.error = error
    if node_executions is not None:
        execution.node_executions = node_executions

    if execution.status in [ExecutionStatus.COMPLETED, ExecutionStatus.FAILED, ExecutionStatus.CANCELLED]:
        execution.completed_at = datetime.now()

    await db.commit()

    return ApiResponse(data={"message": "Execution updated"}, meta=create_meta(request))


# ============================================
# 成本记录
# ============================================

@router.post("/cost-records", response_model=ApiResponse)
async def internal_record_cost(
    request: Request,
    tenant_id: UUID = Body(...),
    user_id: Optional[UUID] = Body(None),
    model_id: str = Body(...),
    model_provider: str = Body(...),
    operation_type: str = Body(...),
    prompt_tokens: int = Body(...),
    completion_tokens: int = Body(...),
    total_tokens: int = Body(...),
    estimated_cost: float = Body(...),
    currency: str = Body("USD"),
    metadata: Optional[Dict] = Body(None),
    db: AsyncSession = Depends(get_async_db),
    _: bool = Depends(require_service_auth),
):
    """内部服务记录成本 (llm-service/rag-service 调用)"""
    cost = CostRecord(
        tenant_id=tenant_id,
        user_id=user_id,
        model_id=model_id,
        model_provider=ModelProvider(model_provider),
        operation_type=operation_type,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        estimated_cost=estimated_cost,
        currency=currency,
        meta=metadata,
    )
    db.add(cost)

    # 更新 Token 预算
    budget_result = await db.execute(
        select(TokenBudget).where(
            TokenBudget.tenant_id == tenant_id,
            TokenBudget.period == "monthly",
        )
    )
    budget = budget_result.scalar_one_or_none()
    if budget:
        budget.used += total_tokens

    await db.commit()

    return ApiResponse(data={"message": "Cost recorded"}, meta=create_meta(request))


# ============================================
# 模型配置
# ============================================

@router.get("/models/{model_id}", response_model=ApiResponse)
async def internal_get_model(
    request: Request,
    model_id: str,
    db: AsyncSession = Depends(get_async_db),
    _: bool = Depends(require_service_auth),
):
    """内部服务获取模型配置"""
    result = await db.execute(select(Model).where(Model.id == model_id))
    model = result.scalar_one_or_none()

    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model not found",
        )

    return ApiResponse(data={
        "id": model.id,
        "name": model.name,
        "provider": model.provider.value,
        "capabilities": [c.value for c in model.capabilities],
        "context_window": model.context_window,
        "max_output_tokens": model.max_output_tokens,
        "pricing": model.pricing,
        "parameters": model.parameters,
    }, meta=create_meta(request))


@router.get("/models", response_model=ApiResponse)
async def internal_list_models(
    request: Request,
    provider: Optional[str] = Query(None),
    capability: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_async_db),
    _: bool = Depends(require_service_auth),
):
    """内部服务获取模型列表"""
    query = select(Model).where(Model.enabled == True)

    if provider:
        query = query.where(Model.provider == provider)

    if capability:
        query = query.where(Model.capabilities.contains([capability]))

    result = await db.execute(query)
    models = result.scalars().all()

    return ApiResponse(data=[{
        "id": m.id,
        "name": m.name,
        "provider": m.provider.value,
        "capabilities": [c.value for c in m.capabilities],
        "context_window": m.context_window,
        "max_output_tokens": m.max_output_tokens,
        "pricing": m.pricing,
        "parameters": m.parameters,
    } for m in models], meta=create_meta(request))


# ============================================
# 检查权限
# ============================================

@router.post("/check-permission", response_model=ApiResponse)
async def internal_check_permission(
    request: Request,
    user_id: UUID = Body(...),
    permission: str = Body(...),
    db: AsyncSession = Depends(get_async_db),
    _: bool = Depends(require_service_auth),
):
    """内部服务检查用户权限"""
    result = await db.execute(
        select(User).where(User.id == user_id, User.deleted_at.is_(None))
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    from app.core.security import get_role_permissions, has_permission
    user_perms = get_role_permissions(user.role.value)
    allowed = has_permission(user_perms, permission)

    return ApiResponse(data={"allowed": allowed}, meta=create_meta(request))


# ============================================
# 向量搜索 (供 RAG 服务调用)
# ============================================

@router.post("/vector-search", response_model=ApiResponse)
async def internal_vector_search(
    request: Request,
    knowledge_base_id: UUID = Body(...),
    query_embedding: List[float] = Body(...),
    top_k: int = Body(5),
    score_threshold: float = Body(0.7),
    filter_metadata: Optional[Dict] = Body(None),
    db: AsyncSession = Depends(get_async_db),
    _: bool = Depends(require_service_auth),
):
    """内部向量搜索 (简化版，实际应使用 pgvector 原生查询)"""
    # 这里只是示例，实际向量搜索应在 RAG 服务中使用原生 SQL
    # 或通过 pgvector 的 SQL 函数

    # 获取知识库配置
    kb_result = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.id == knowledge_base_id)
    )
    kb = kb_result.scalar_one_or_none()

    if not kb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge base not found",
        )

    # 实际实现需要使用原生 SQL 进行向量相似度搜索
    # 这里返回空结果
    return ApiResponse(data={
        "results": [],
        "message": "Vector search should be implemented in RAG service with native pgvector queries",
    }, meta=create_meta(request))