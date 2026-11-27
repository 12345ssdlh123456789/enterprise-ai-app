# API Gateway - Conversations Routes

import asyncio
import json
from datetime import datetime, timezone
from typing import Optional, List
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import get_current_user, get_current_tenant, get_role_permissions, has_permission
from app.db.session import get_async_db
from app.models import Conversation, Message, KnowledgeBase, MessageRole, User, Tenant
from app.services.llm import chat as llm_chat
from app.services.retrieval import build_rag_context, retrieve_chunks
from app.schemas import (
    ConversationCreate,
    ConversationUpdate,
    ConversationResponse,
    ConversationListItem,
    MessageCreate,
    MessageResponse,
    ChatCompletionRequest,
    ChatCompletionChunk,
    CitationSchema,
    TokenUsage,
    PaginationParams,
    PaginatedResponse,
    ApiResponse,
    ResponseMeta,
)

router = APIRouter(prefix="/conversations", tags=["Conversations"])


def create_meta(request: Request) -> ResponseMeta:
    return ResponseMeta(
        request_id=getattr(request.state, "request_id", "unknown"),
        timestamp=datetime.now(timezone.utc),
        version=settings.APP_VERSION,
    )


def conv_to_list_item(conv: Conversation) -> ConversationListItem:
    return ConversationListItem(
        id=conv.id,
        title=conv.title,
        model=conv.model,
        message_count=conv.message_count,
        total_tokens=conv.total_tokens,
        updated_at=conv.updated_at,
    )


def conv_to_response(conv: Conversation, messages: Optional[List[Message]] = None) -> ConversationResponse:
    msg_responses = None
    if messages:
        msg_responses = [
            MessageResponse(
                id=m.id,
                conversation_id=m.conversation_id,
                role=m.role.value,
                content=m.content,
                token_count=m.token_count,
                model=m.model,
                citations=[CitationSchema(**c) for c in m.citations] if m.citations else None,
                metadata=m.meta,
                created_at=m.created_at,
            )
            for m in messages
        ]

    return ConversationResponse(
        id=conv.id,
        tenant_id=conv.tenant_id,
        knowledge_base_id=conv.knowledge_base_id,
        title=conv.title,
        model=conv.model,
        system_prompt=conv.system_prompt,
        temperature=float(conv.temperature),
        max_tokens=conv.max_tokens,
        message_count=conv.message_count,
        total_tokens=conv.total_tokens,
        created_by=conv.created_by,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        messages=msg_responses,
    )


# ============================================
# RAG / Ollama 辅助函数
# ============================================

def _build_ollama_messages(
    system_prompt: Optional[str],
    history_messages: List[Message],
    rag_context: str,
    user_content: str,
) -> List[dict]:
    """构建发给 ollama 的 messages 列表。"""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if rag_context:
        messages.append(
            {
                "role": "system",
                "content": f"以下是从知识库检索到的相关内容，请在回答中引用：\n\n{rag_context}",
            }
        )
    for m in history_messages:
        role = m.role.value if hasattr(m.role, "value") else str(m.role)
        messages.append({"role": role, "content": m.content})
    messages.append({"role": "user", "content": user_content})
    return messages


async def _ollama_chat_stream(
    messages: List[dict],
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 2048,
):
    """调用 ollama /api/chat（流式），逐条返回 (content, done)。"""
    url = f"{settings.OLLAMA_BASE_URL}/api/chat"
    payload = {
        "model": model or settings.OLLAMA_CHAT_MODEL,
        "messages": messages,
        "stream": True,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        async with client.stream("POST", url, json=payload) as resp:
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = data.get("message", {})
                content = msg.get("content", "")
                done = data.get("done", False)
                yield content, done


# ============================================
# 获取对话列表
# ============================================

@router.get("", response_model=ApiResponse[PaginatedResponse[ConversationListItem]])
async def list_conversations(
    request: Request,
    pagination: PaginationParams = Depends(),
    knowledge_base_id: Optional[UUID] = Query(None, description="按知识库筛选"),
    search: Optional[str] = Query(None, description="搜索标题"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """获取对话列表"""
    user_perms = get_role_permissions(current_user.role.value)
    if not has_permission(user_perms, "chat:read"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: chat:read",
        )

    query = select(Conversation).where(
        Conversation.tenant_id == current_tenant.id,
        Conversation.deleted_at.is_(None),
    )
    count_query = select(func.count(Conversation.id)).where(
        Conversation.tenant_id == current_tenant.id,
        Conversation.deleted_at.is_(None),
    )

    if knowledge_base_id:
        query = query.where(Conversation.knowledge_base_id == knowledge_base_id)
        count_query = count_query.where(Conversation.knowledge_base_id == knowledge_base_id)

    if search:
        search_term = f"%{search}%"
        query = query.where(Conversation.title.ilike(search_term))
        count_query = count_query.where(Conversation.title.ilike(search_term))

    # 非管理员只能看自己的对话
    if current_user.role.value not in ["SUPER_ADMIN", "ADMIN"]:
        query = query.where(Conversation.created_by == current_user.id)
        count_query = count_query.where(Conversation.created_by == current_user.id)

    query = query.order_by(desc(Conversation.updated_at))
    offset = (pagination.page - 1) * pagination.page_size
    query = query.offset(offset).limit(pagination.page_size)

    result = await db.execute(query)
    convs = result.scalars().all()

    count_result = await db.execute(count_query)
    total = count_result.scalar()

    items = [conv_to_list_item(c) for c in convs]
    paginated = PaginatedResponse.create(items, total, pagination)

    return ApiResponse(data=paginated, meta=create_meta(request))


# ============================================
# 创建对话
# ============================================

@router.post("", response_model=ApiResponse[ConversationResponse], status_code=status.HTTP_201_CREATED)
async def create_conversation(
    request: Request,
    conv_data: ConversationCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """创建新对话"""
    user_perms = get_role_permissions(current_user.role.value)
    if not has_permission(user_perms, "chat:create"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: chat:create",
        )

    # 验证知识库 (如果指定)
    if conv_data.knowledge_base_id:
        kb_result = await db.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.id == conv_data.knowledge_base_id,
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

        # 检查可见性
        if kb.visibility.value == "PRIVATE" and kb.created_by != current_user.id:
            if not has_permission(user_perms, "knowledge-base:read"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Permission denied: knowledge base is private",
                )

    conv = Conversation(
        tenant_id=current_tenant.id,
        knowledge_base_id=conv_data.knowledge_base_id,
        title=conv_data.title,
        model=conv_data.model,
        system_prompt=conv_data.system_prompt,
        temperature=conv_data.temperature,
        max_tokens=conv_data.max_tokens,
        created_by=current_user.id,
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)

    return ApiResponse(data=conv_to_response(conv), meta=create_meta(request))


# ============================================
# 获取单个对话 (含消息)
# ============================================

@router.get("/{conv_id}", response_model=ApiResponse[ConversationResponse])
async def get_conversation(
    request: Request,
    conv_id: UUID,
    include_messages: bool = Query(True, description="是否包含消息"),
    message_limit: int = Query(50, ge=1, le=200, description="消息数量限制"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """获取对话详情 (可选包含消息)"""
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.tenant_id == current_tenant.id,
            Conversation.deleted_at.is_(None),
        )
    )
    conv = result.scalar_one_or_none()

    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    # 权限检查
    user_perms = get_role_permissions(current_user.role.value)
    if conv.created_by != current_user.id and not has_permission(user_perms, "chat:read"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: not owner or admin",
        )

    messages = None
    if include_messages:
        msg_result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conv_id)
            .order_by(Message.created_at)
            .limit(message_limit)
        )
        messages = msg_result.scalars().all()

    return ApiResponse(data=conv_to_response(conv, messages), meta=create_meta(request))


# ============================================
# 更新对话
# ============================================

@router.patch("/{conv_id}", response_model=ApiResponse[ConversationResponse])
async def update_conversation(
    request: Request,
    conv_id: UUID,
    conv_data: ConversationUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """更新对话设置"""
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.tenant_id == current_tenant.id,
            Conversation.deleted_at.is_(None),
        )
    )
    conv = result.scalar_one_or_none()

    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    user_perms = get_role_permissions(current_user.role.value)
    if conv.created_by != current_user.id and not has_permission(user_perms, "chat:update"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied",
        )

    update_data = conv_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(conv, field, value)

    await db.commit()
    await db.refresh(conv)

    return ApiResponse(data=conv_to_response(conv), meta=create_meta(request))


# ============================================
# 删除对话
# ============================================

@router.delete("/{conv_id}", response_model=ApiResponse)
async def delete_conversation(
    request: Request,
    conv_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """删除对话 (软删除)"""
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.tenant_id == current_tenant.id,
            Conversation.deleted_at.is_(None),
        )
    )
    conv = result.scalar_one_or_none()

    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    user_perms = get_role_permissions(current_user.role.value)
    if conv.created_by != current_user.id and not has_permission(user_perms, "chat:delete"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied",
        )

    conv.deleted_at = datetime.now(timezone.utc)

    await db.commit()

    return ApiResponse(data={"message": "Conversation deleted successfully"}, meta=create_meta(request))


# ============================================
# 获取对话消息
# ============================================

@router.get("/{conv_id}/messages", response_model=ApiResponse[PaginatedResponse[MessageResponse]])
async def list_messages(
    request: Request,
    conv_id: UUID,
    pagination: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """获取对话消息列表 (分页，最新在前)"""
    # 验证对话权限
    conv_result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.tenant_id == current_tenant.id,
            Conversation.deleted_at.is_(None),
        )
    )
    conv = conv_result.scalar_one_or_none()

    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    user_perms = get_role_permissions(current_user.role.value)
    if conv.created_by != current_user.id and not has_permission(user_perms, "chat:read"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied",
        )

    query = select(Message).where(Message.conversation_id == conv_id).order_by(desc(Message.created_at))
    count_query = select(func.count(Message.id)).where(Message.conversation_id == conv_id)

    offset = (pagination.page - 1) * pagination.page_size
    query = query.offset(offset).limit(pagination.page_size)

    result = await db.execute(query)
    msgs = result.scalars().all()

    count_result = await db.execute(count_query)
    total = count_result.scalar()

    items = [
        MessageResponse(
            id=m.id,
            conversation_id=m.conversation_id,
            role=m.role.value,
            content=m.content,
            token_count=m.token_count,
            model=m.model,
            citations=[CitationSchema(**c) for c in m.citations] if m.citations else None,
            metadata=m.meta,
            created_at=m.created_at,
        )
        for m in reversed(msgs)  # 反转为时间正序
    ]

    paginated = PaginatedResponse.create(items, total, pagination)

    return ApiResponse(data=paginated, meta=create_meta(request))


# ============================================
# 发送消息 (非流式)
# ============================================

@router.post("/{conv_id}/messages", response_model=ApiResponse[MessageResponse])
async def send_message(
    request: Request,
    conv_id: UUID,
    message_data: MessageCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """发送消息 (非流式，等待完整回复)"""
    # 验证对话
    conv_result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id,
            Conversation.tenant_id == current_tenant.id,
            Conversation.deleted_at.is_(None),
        )
    )
    conv = conv_result.scalar_one_or_none()

    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    user_perms = get_role_permissions(current_user.role.value)
    if conv.created_by != current_user.id and not has_permission(user_perms, "chat:create"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied",
        )

    # 保存用户消息
    user_msg = Message(
        conversation_id=conv_id,
        role=MessageRole.USER,
        content=message_data.content,
    )
    db.add(user_msg)

    # RAG 检索（如对话关联知识库）
    rag_chunks: List[dict] = []
    if settings.ENABLE_RAG and conv.knowledge_base_id:
        rag_chunks = await retrieve_chunks(
            db, conv.knowledge_base_id, message_data.content, top_k=settings.DEFAULT_TOP_K
        )
    rag_context = build_rag_context(rag_chunks)

    # 加载历史消息（最近 20 条）
    hist_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.desc())
        .limit(20)
    )
    history = list(reversed(hist_result.scalars().all()))

    # 构建 ollama messages
    ollama_messages = _build_ollama_messages(
        conv.system_prompt,
        history,
        rag_context,
        message_data.content,
    )

    # 调用 ollama 生成回复
    try:
        assistant_content = (await llm_chat(
            messages=ollama_messages,
            model=settings.OLLAMA_CHAT_MODEL,
            temperature=float(conv.temperature or 0.7),
            max_tokens=int(conv.max_tokens or 2048),
        )).content
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Ollama 调用失败: {exc}",
        )

    # 引用
    citations = None
    if rag_chunks:
        citations = [
            CitationSchema(
                document_id=str(c["document_id"]),
                document_title=c["document_filename"],
                chunk_id=str(c["chunk_id"]),
                chunk_content=c["content"],
                score=c["score"],
            )
            for c in rag_chunks
        ]

    assistant_msg = Message(
        conversation_id=conv_id,
        role=MessageRole.ASSISTANT,
        content=assistant_content,
        model=conv.model,
        citations=[c.model_dump() for c in citations] if citations else None,
    )
    db.add(assistant_msg)

    # 更新对话统计
    conv.message_count += 2
    conv.updated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(assistant_msg)

    return ApiResponse(
        data=MessageResponse(
            id=assistant_msg.id,
            conversation_id=assistant_msg.conversation_id,
            role=assistant_msg.role.value,
            content=assistant_msg.content,
            token_count=assistant_msg.token_count,
            model=assistant_msg.model,
            citations=[CitationSchema(**c) for c in assistant_msg.citations] if assistant_msg.citations else None,
            metadata=assistant_msg.meta,
            created_at=assistant_msg.created_at,
        ),
        meta=create_meta(request),
    )


# ============================================
# 流式聊天完成
# ============================================

@router.post("/chat/completions", response_model=None)
async def chat_completions(
    request: Request,
    chat_request: ChatCompletionRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """流式聊天完成 (SSE)"""
    # 验证权限
    user_perms = get_role_permissions(current_user.role.value)
    if not has_permission(user_perms, "chat:create"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: chat:create",
        )

    # 获取或创建对话
    conversation = None
    if chat_request.conversation_id:
        conv_result = await db.execute(
            select(Conversation).where(
                Conversation.id == chat_request.conversation_id,
                Conversation.tenant_id == current_tenant.id,
                Conversation.deleted_at.is_(None),
            )
        )
        conversation = conv_result.scalar_one_or_none()
        if not conversation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )
        if conversation.created_by != current_user.id and not has_permission(user_perms, "chat:read"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied",
            )
    else:
        # 创建新对话
        conversation = Conversation(
            tenant_id=current_tenant.id,
            knowledge_base_id=chat_request.knowledge_base_id,
            title="新对话",
            model=chat_request.model or "gpt-4o-mini",
            temperature=chat_request.temperature or 0.7,
            max_tokens=chat_request.max_tokens or 2048,
            created_by=current_user.id,
        )
        db.add(conversation)
        await db.flush()

    # 保存用户消息
    user_messages = chat_request.messages
    for msg in user_messages:
        if msg.role == "user":
            user_msg = Message(
                conversation_id=conversation.id,
                role=MessageRole.USER,
                content=msg.content,
            )
            db.add(user_msg)

    await db.commit()

    # RAG 检索（如对话关联知识库）
    rag_chunks: List[dict] = []
    if settings.ENABLE_RAG and conversation.knowledge_base_id:
        rag_chunks = await retrieve_chunks(
            db, conversation.knowledge_base_id,
            user_messages[-1].content if user_messages else "",
            top_k=settings.DEFAULT_TOP_K,
        )
    rag_context = build_rag_context(rag_chunks)

    # 加载历史消息（最近 20 条）
    hist_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.desc())
        .limit(20)
    )
    history = list(reversed(hist_result.scalars().all()))

    # 构建 ollama messages（把前端传来的全部 messages 放入历史）
    ollama_messages = _build_ollama_messages(
        conversation.system_prompt,
        history,
        rag_context,
        user_messages[-1].content if user_messages else "",
    )

    # 调用 ollama 生成回复
    try:
        assistant_content = (await llm_chat(
            messages=ollama_messages,
            model=settings.OLLAMA_CHAT_MODEL,
            temperature=float(conversation.temperature or 0.7),
            max_tokens=int(conversation.max_tokens or 2048),
        )).content
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Ollama 调用失败: {exc}",
        )

    # 引用
    citations = None
    if rag_chunks:
        citations = [
            CitationSchema(
                document_id=str(c["document_id"]),
                document_title=c["document_filename"],
                chunk_id=str(c["chunk_id"]),
                chunk_content=c["content"],
                score=c["score"],
            )
            for c in rag_chunks
        ]

    assistant_msg = Message(
        conversation_id=conversation.id,
        role=MessageRole.ASSISTANT,
        content=assistant_content,
        model=conversation.model,
        citations=[c.model_dump() for c in citations] if citations else None,
    )
    db.add(assistant_msg)
    conversation.message_count += len(user_messages) + 1
    await db.commit()
    await db.refresh(assistant_msg)

    if chat_request.stream:
        # 流式：把 ollama 完整回复按 SSE 分片发出
        async def generate_stream():
            from uuid import uuid4

            chunk_size = 20
            for i in range(0, len(assistant_content), chunk_size):
                chunk = assistant_content[i:i + chunk_size]
                chunk_data = ChatCompletionChunk(
                    id=str(uuid4()),
                    conversation_id=conversation.id,
                    delta=chunk,
                    finished=False,
                )
                yield f"data: {chunk_data.model_dump_json()}\n\n"
                await asyncio.sleep(0.02)

            final_chunk = ChatCompletionChunk(
                id=str(uuid4()),
                conversation_id=conversation.id,
                delta="",
                finished=True,
                citations=[c.model_dump() for c in citations] if citations else None,
                usage=TokenUsage(
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                ),
            )
            yield f"data: {final_chunk.model_dump_json()}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            generate_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        # 非流式：直接返回完整回复
        return ApiResponse(
            data=MessageResponse(
                id=assistant_msg.id,
                conversation_id=assistant_msg.conversation_id,
                role=assistant_msg.role.value,
                content=assistant_msg.content,
                token_count=assistant_msg.token_count,
                model=assistant_msg.model,
                citations=[CitationSchema(**c) for c in assistant_msg.citations] if assistant_msg.citations else None,
                metadata=assistant_msg.meta,
                created_at=assistant_msg.created_at,
            ),
            meta=create_meta(request),
        )
