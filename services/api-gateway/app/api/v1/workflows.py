# API Gateway - Workflows Routes

from datetime import datetime, timezone
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from sqlalchemy import select, func, desc, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import get_current_user, get_current_tenant, get_role_permissions, has_permission
from app.db.session import get_async_db
from app.models import (
    Workflow,
    WorkflowExecution,
    ExecutionStatus,
    User,
    Tenant,
    WorkflowStatus,
    NotificationType,
)
from app.services.notify import notify
from app.services.workflow_runner import RunContext, WorkflowRunError, RunResult, run_workflow
from app.schemas import (
    WorkflowCreate,
    WorkflowUpdate,
    WorkflowResponse,
    WorkflowListItem,
    WorkflowExecutionRequest,
    WorkflowExecutionResponse,
    WorkflowDefinitionSchema,
    PaginationParams,
    PaginatedResponse,
    ApiResponse,
    ResponseMeta,
)

router = APIRouter(prefix="/workflows", tags=["Workflows"])


def create_meta(request: Request) -> ResponseMeta:
    return ResponseMeta(
        request_id=getattr(request.state, "request_id", "unknown"),
        timestamp=datetime.now(timezone.utc),
        version=settings.APP_VERSION,
    )


def wf_to_list_item(wf: Workflow) -> WorkflowListItem:
    return WorkflowListItem(
        id=wf.id,
        name=wf.name,
        description=wf.description,
        status=wf.status.value,
        version=wf.version,
        created_at=wf.created_at,
        updated_at=wf.updated_at,
    )


def execution_to_response(execution: WorkflowExecution) -> WorkflowExecutionResponse:
    """执行记录 → 响应；`node_executions` 历史数据可能是 `{}`，统一成列表。"""
    nodes = execution.node_executions if isinstance(execution.node_executions, list) else []
    return WorkflowExecutionResponse(
        id=execution.id,
        workflow_id=execution.workflow_id,
        tenant_id=execution.tenant_id,
        status=execution.status.value,
        input=execution.input or {},
        output=execution.output,
        error=execution.error,
        started_at=execution.started_at,
        completed_at=execution.completed_at,
        node_executions=nodes,
    )


async def _notify_execution(wf: Workflow, execution: WorkflowExecution, user_id) -> None:
    """执行结果写成站内通知（第 28 轮的 notify 出口，两种通知后端都走同一条路）。"""
    duration_ms = 0
    if execution.started_at and execution.completed_at:
        duration_ms = max(0, int((execution.completed_at - execution.started_at).total_seconds() * 1000))
    data = {
        "workflow_id": str(execution.workflow_id),
        "execution_id": str(execution.id),
        "status": execution.status.value,
        "event": "workflow.execution.finished",
    }
    if execution.status == ExecutionStatus.COMPLETED:
        node_count = len(execution.node_executions or []) if isinstance(execution.node_executions, list) else 0
        await notify(
            tenant_id=execution.tenant_id,
            user_id=user_id,
            type=NotificationType.SUCCESS,
            title=f"工作流「{wf.name}」执行完成",
            content=f"共执行 {node_count} 个节点，耗时 {duration_ms} ms。",
            data=data,
        )
    else:
        await notify(
            tenant_id=execution.tenant_id,
            user_id=user_id,
            type=NotificationType.ERROR,
            title=f"工作流「{wf.name}」执行失败",
            content=execution.error or "执行器返回了未知错误，可以查看执行记录详情。",
            data=data,
        )


def wf_to_response(wf: Workflow) -> WorkflowResponse:
    return WorkflowResponse(
        id=wf.id,
        tenant_id=wf.tenant_id,
        name=wf.name,
        description=wf.description,
        definition=WorkflowDefinitionSchema(**wf.definition),
        status=wf.status.value,
        version=wf.version,
        created_by=wf.created_by,
        created_at=wf.created_at,
        updated_at=wf.updated_at,
        published_at=wf.published_at,
    )


# ============================================
# 校验工作流定义（前端“验证”按钮）
# ============================================

@router.post("/validate", response_model=ApiResponse)
async def validate_workflow_definition(
    request: Request,
    definition: WorkflowDefinitionSchema,
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    errors: List[str] = []
    warnings: List[str] = []

    node_ids = {node.id for node in definition.nodes}
    if not definition.nodes:
        errors.append("工作流至少需要一个节点")

    for node in definition.nodes:
        if not (node.name or "").strip():
            errors.append(f"节点 {node.id} 缺少名称")

    for edge in definition.edges:
        if edge.source_node_id not in node_ids:
            errors.append(f"连线 {edge.id} 的起点节点不存在：{edge.source_node_id}")
        if edge.target_node_id not in node_ids:
            errors.append(f"连线 {edge.id} 的终点节点不存在：{edge.target_node_id}")

    node_types = [(node.type or "").upper() for node in definition.nodes]
    if not any("START" in t for t in node_types):
        warnings.append("建议添加 START 节点作为入口")
    if not any("END" in t for t in node_types):
        warnings.append("建议添加 END 节点作为出口")

    return ApiResponse(
        data={"valid": not errors, "errors": errors, "warnings": warnings},
        meta=create_meta(request),
    )


# ============================================
# 获取工作流列表
# ============================================

@router.get("", response_model=ApiResponse[PaginatedResponse[WorkflowListItem]])
async def list_workflows(
    request: Request,
    pagination: PaginationParams = Depends(),
    search: Optional[str] = Query(None, description="搜索名称、描述"),
    status: Optional[str] = Query(None, description="按状态筛选"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """获取工作流列表"""
    user_perms = get_role_permissions(current_user.role.value)
    if not has_permission(user_perms, "workflow:read"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: workflow:read",
        )

    query = select(Workflow).where(
        Workflow.tenant_id == current_tenant.id,
        Workflow.deleted_at.is_(None),
    )
    count_query = select(func.count(Workflow.id)).where(
        Workflow.tenant_id == current_tenant.id,
        Workflow.deleted_at.is_(None),
    )

    if search:
        search_term = f"%{search}%"
        query = query.where(
            or_(
                Workflow.name.ilike(search_term),
                Workflow.description.ilike(search_term),
            )
        )
        count_query = count_query.where(
            or_(
                Workflow.name.ilike(search_term),
                Workflow.description.ilike(search_term),
            )
        )

    if status:
        query = query.where(Workflow.status == status)
        count_query = count_query.where(Workflow.status == status)

    # 非管理员只能看自己的
    if current_user.role.value not in ["SUPER_ADMIN", "ADMIN"]:
        query = query.where(Workflow.created_by == current_user.id)
        count_query = count_query.where(Workflow.created_by == current_user.id)

    query = query.order_by(desc(Workflow.updated_at))
    offset = (pagination.page - 1) * pagination.page_size
    query = query.offset(offset).limit(pagination.page_size)

    result = await db.execute(query)
    wfs = result.scalars().all()

    count_result = await db.execute(count_query)
    total = count_result.scalar()

    items = [wf_to_list_item(w) for w in wfs]
    paginated = PaginatedResponse.create(items, total, pagination)

    return ApiResponse(data=paginated, meta=create_meta(request))


# ============================================
# 创建工作流
# ============================================

@router.post("", response_model=ApiResponse[WorkflowResponse], status_code=status.HTTP_201_CREATED)
async def create_workflow(
    request: Request,
    wf_data: WorkflowCreate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """创建工作流"""
    user_perms = get_role_permissions(current_user.role.value)
    if not has_permission(user_perms, "workflow:create"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: workflow:create",
        )

    wf = Workflow(
        tenant_id=current_tenant.id,
        name=wf_data.name,
        description=wf_data.description,
        definition=wf_data.definition.model_dump(),
        status=WorkflowStatus.DRAFT,
        created_by=current_user.id,
    )
    db.add(wf)
    await db.commit()
    await db.refresh(wf)

    return ApiResponse(data=wf_to_response(wf), meta=create_meta(request))


# ============================================
# 获取单个工作流
# ============================================

@router.get("/{wf_id}", response_model=ApiResponse[WorkflowResponse])
async def get_workflow(
    request: Request,
    wf_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """获取工作流详情"""
    result = await db.execute(
        select(Workflow).where(
            Workflow.id == wf_id,
            Workflow.tenant_id == current_tenant.id,
            Workflow.deleted_at.is_(None),
        )
    )
    wf = result.scalar_one_or_none()

    if not wf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found",
        )

    user_perms = get_role_permissions(current_user.role.value)
    if wf.created_by != current_user.id and not has_permission(user_perms, "workflow:read"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied",
        )

    return ApiResponse(data=wf_to_response(wf), meta=create_meta(request))


# ============================================
# 更新工作流
# ============================================

@router.patch("/{wf_id}", response_model=ApiResponse[WorkflowResponse])
async def update_workflow(
    request: Request,
    wf_id: UUID,
    wf_data: WorkflowUpdate,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """更新工作流"""
    result = await db.execute(
        select(Workflow).where(
            Workflow.id == wf_id,
            Workflow.tenant_id == current_tenant.id,
            Workflow.deleted_at.is_(None),
        )
    )
    wf = result.scalar_one_or_none()

    if not wf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found",
        )

    user_perms = get_role_permissions(current_user.role.value)
    if wf.created_by != current_user.id and not has_permission(user_perms, "workflow:update"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied",
        )

    update_data = wf_data.model_dump(exclude_unset=True)

    if "definition" in update_data and update_data["definition"]:
        # model_dump() 已把嵌套模型转成 dict，这里要兼容两种形态
        definition = update_data["definition"]
        if hasattr(definition, "model_dump"):
            definition = definition.model_dump()
        update_data["definition"] = definition

    for field, value in update_data.items():
        setattr(wf, field, value)

    # 如果定义变更，版本号+1
    if "definition" in update_data:
        wf.version += 1

    await db.commit()
    await db.refresh(wf)

    return ApiResponse(data=wf_to_response(wf), meta=create_meta(request))


# ============================================
# 删除工作流
# ============================================

@router.delete("/{wf_id}", response_model=ApiResponse)
async def delete_workflow(
    request: Request,
    wf_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """删除工作流 (软删除)"""
    result = await db.execute(
        select(Workflow).where(
            Workflow.id == wf_id,
            Workflow.tenant_id == current_tenant.id,
            Workflow.deleted_at.is_(None),
        )
    )
    wf = result.scalar_one_or_none()

    if not wf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found",
        )

    user_perms = get_role_permissions(current_user.role.value)
    if wf.created_by != current_user.id and not has_permission(user_perms, "workflow:delete"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied",
        )

    from datetime import datetime, timezone
    wf.deleted_at = datetime.now(timezone.utc)

    await db.commit()

    return ApiResponse(data={"message": "Workflow deleted successfully"}, meta=create_meta(request))


# ============================================
# 发布/取消发布工作流
# ============================================

@router.post("/{wf_id}/publish", response_model=ApiResponse[WorkflowResponse])
async def publish_workflow(
    request: Request,
    wf_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """发布工作流 (设为 ACTIVE)"""
    result = await db.execute(
        select(Workflow).where(
            Workflow.id == wf_id,
            Workflow.tenant_id == current_tenant.id,
            Workflow.deleted_at.is_(None),
        )
    )
    wf = result.scalar_one_or_none()

    if not wf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found",
        )

    user_perms = get_role_permissions(current_user.role.value)
    if wf.created_by != current_user.id and not has_permission(user_perms, "workflow:update"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied",
        )

    from datetime import datetime, timezone
    wf.status = WorkflowStatus.ACTIVE
    wf.published_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(wf)

    return ApiResponse(data=wf_to_response(wf), meta=create_meta(request))


@router.post("/{wf_id}/unpublish", response_model=ApiResponse[WorkflowResponse])
async def unpublish_workflow(
    request: Request,
    wf_id: UUID,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """取消发布工作流 (设为 PAUSED)"""
    result = await db.execute(
        select(Workflow).where(
            Workflow.id == wf_id,
            Workflow.tenant_id == current_tenant.id,
            Workflow.deleted_at.is_(None),
        )
    )
    wf = result.scalar_one_or_none()

    if not wf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found",
        )

    user_perms = get_role_permissions(current_user.role.value)
    if wf.created_by != current_user.id and not has_permission(user_perms, "workflow:update"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied",
        )

    wf.status = WorkflowStatus.PAUSED

    await db.commit()
    await db.refresh(wf)

    return ApiResponse(data=wf_to_response(wf), meta=create_meta(request))


# ============================================
# 执行工作流
# ============================================

@router.post("/{wf_id}/execute", response_model=ApiResponse[WorkflowExecutionResponse])
async def execute_workflow(
    request: Request,
    wf_id: UUID,
    exec_data: WorkflowExecutionRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """执行工作流"""
    result = await db.execute(
        select(Workflow).where(
            Workflow.id == wf_id,
            Workflow.tenant_id == current_tenant.id,
            Workflow.deleted_at.is_(None),
        )
    )
    wf = result.scalar_one_or_none()

    if not wf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found",
        )

    if wf.status != WorkflowStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Workflow is not active",
        )

    user_perms = get_role_permissions(current_user.role.value)
    if not has_permission(user_perms, "workflow:execute"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: workflow:execute",
        )

    # 创建执行记录（input 与 input_data 两种字段名都接受）
    input_payload = exec_data.input or exec_data.input_data or {}
    execution = WorkflowExecution(
        workflow_id=wf_id,
        tenant_id=current_tenant.id,
        status=ExecutionStatus.RUNNING,
        input=input_payload,
    )
    db.add(execution)
    await db.commit()
    await db.refresh(execution)

    # 默认模式在进程内执行（START / END / HTTP / DELAY）；要真跑 LLM、知识检索、条件分支，
    # 请开 GATEWAY_PROXY_WORKFLOWS 交给 workflow-service（见 proxy_workflows.py）。
    try:
        result = await run_workflow(
            wf.definition,
            input_payload,
            ctx=RunContext(db=db, tenant_id=current_tenant.id, user_id=current_user.id),
        )
    except WorkflowRunError as exc:
        result = RunResult(status="failed", output=None, error=str(exc), nodes=[], duration_ms=0)

    execution.status = (
        ExecutionStatus.COMPLETED if result.status == "completed" else ExecutionStatus.FAILED
    )
    execution.output = result.output
    execution.error = result.error
    execution.node_executions = result.nodes
    execution.completed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(execution)

    await _notify_execution(wf, execution, current_user.id)

    return ApiResponse(data=execution_to_response(execution), meta=create_meta(request))


# ============================================
# 获取执行记录
# ============================================

@router.get("/{wf_id}/executions", response_model=ApiResponse[PaginatedResponse[WorkflowExecutionResponse]])
async def list_workflow_executions(
    request: Request,
    wf_id: UUID,
    pagination: PaginationParams = Depends(),
    status: Optional[str] = Query(None, description="按状态筛选"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """获取工作流执行历史"""
    user_perms = get_role_permissions(current_user.role.value)
    if not has_permission(user_perms, "workflow:read"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: workflow:read",
        )

    query = select(WorkflowExecution).where(
        WorkflowExecution.workflow_id == wf_id,
        WorkflowExecution.tenant_id == current_tenant.id,
    )
    count_query = select(func.count(WorkflowExecution.id)).where(
        WorkflowExecution.workflow_id == wf_id,
        WorkflowExecution.tenant_id == current_tenant.id,
    )

    if status:
        query = query.where(WorkflowExecution.status == status)
        count_query = count_query.where(WorkflowExecution.status == status)

    query = query.order_by(desc(WorkflowExecution.started_at))
    offset = (pagination.page - 1) * pagination.page_size
    query = query.offset(offset).limit(pagination.page_size)

    result = await db.execute(query)
    executions = result.scalars().all()

    count_result = await db.execute(count_query)
    total = count_result.scalar()

    items = [execution_to_response(e) for e in executions]

    paginated = PaginatedResponse.create(items, total, pagination)

    return ApiResponse(data=paginated, meta=create_meta(request))
