from uuid import UUID
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Response, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.db.session import get_session
from app.schemas import (
    WorkflowCreate,
    WorkflowUpdate,
    WorkflowRead,
    WorkflowVersionRead,
    WorkflowExecutionRead,
    WorkflowExecutionLogRead,
    WorkflowPublishRequest,
    WorkflowExecuteRequest,
    WorkflowCancelRequest,
    NodeTemplateCreate,
    NodeTemplateRead,
    WorkflowDefinition,
    ExecutionResult,
)
from app.models import (
    Workflow,
    WorkflowVersion,
    WorkflowExecution,
    WorkflowExecutionLog,
    NodeTemplate,
    WorkflowStatus,
    ExecutionStatus,
)
from app.services.execution_engine import engine
from app.core.context import current_tenant_id, current_user_id

router = APIRouter(prefix="/workflows", tags=["Workflows"])
version_router = APIRouter(prefix="/versions", tags=["Workflow Versions"])
execution_router = APIRouter(prefix="/executions", tags=["Workflow Executions"])
template_router = APIRouter(prefix="/node-templates", tags=["Node Templates"])


async def _get_tenant_workflow(session: AsyncSession, workflow_id: UUID) -> Workflow:
    """按租户取工作流：知道 UUID 也不能跨租户读/改/删/发布/执行。"""
    stmt = select(Workflow).where(
        Workflow.id == workflow_id, Workflow.tenant_id == current_tenant_id()
    )
    workflow = (await session.execute(stmt)).scalar_one_or_none()
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


# Workflow CRUD
@router.post("", response_model=WorkflowRead, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    workflow_in: WorkflowCreate,
    session: AsyncSession = Depends(get_session),
):
    tenant_id = current_tenant_id()

    workflow = Workflow(
        tenant_id=tenant_id,
        created_by=current_user_id(),
        **workflow_in.model_dump(),
    )
    session.add(workflow)
    await session.commit()
    await session.refresh(workflow)
    return workflow


@router.get("", response_model=List[WorkflowRead])
async def list_workflows(
    response: Response,
    session: AsyncSession = Depends(get_session),
    status_filter: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
):
    tenant_id = current_tenant_id()
    stmt = select(Workflow).where(Workflow.tenant_id == tenant_id)
    count_stmt = select(func.count(Workflow.id)).where(Workflow.tenant_id == tenant_id)

    if status_filter:
        stmt = stmt.where(Workflow.status == status_filter)
        count_stmt = count_stmt.where(Workflow.status == status_filter)

    stmt = stmt.order_by(Workflow.updated_at.desc()).offset(skip).limit(limit)
    result = await session.execute(stmt)
    # 总数放响应头：列表体仍是数组，网关转发时用它拼分页信封
    response.headers["X-Total-Count"] = str((await session.execute(count_stmt)).scalar() or 0)
    return result.scalars().all()


@router.get("/{workflow_id}", response_model=WorkflowRead)
async def get_workflow(workflow_id: UUID, session: AsyncSession = Depends(get_session)):
    return await _get_tenant_workflow(session, workflow_id)


@router.patch("/{workflow_id}", response_model=WorkflowRead)
async def update_workflow(
    workflow_id: UUID,
    workflow_in: WorkflowUpdate,
    session: AsyncSession = Depends(get_session),
):
    workflow = await _get_tenant_workflow(session, workflow_id)

    if workflow.status == WorkflowStatus.PUBLISHED:
        raise HTTPException(status_code=400, detail="Cannot modify published workflow. Create a new version.")

    for field, value in workflow_in.model_dump(exclude_unset=True).items():
        setattr(workflow, field, value)

    await session.commit()
    await session.refresh(workflow)
    return workflow


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(workflow_id: UUID, session: AsyncSession = Depends(get_session)):
    workflow = await _get_tenant_workflow(session, workflow_id)

    if workflow.status == WorkflowStatus.PUBLISHED:
        raise HTTPException(status_code=400, detail="Cannot delete published workflow. Archive it first.")

    await session.delete(workflow)
    await session.commit()


@router.post("/{workflow_id}/publish", response_model=WorkflowRead)
async def publish_workflow(
    workflow_id: UUID,
    req: WorkflowPublishRequest,
    session: AsyncSession = Depends(get_session),
):
    workflow = await _get_tenant_workflow(session, workflow_id)

    if workflow.status == WorkflowStatus.PUBLISHED:
        raise HTTPException(status_code=400, detail="Workflow already published")

    # Create version record
    version = WorkflowVersion(
        workflow_id=workflow.id,
        tenant_id=workflow.tenant_id,
        version=workflow.version,
        definition=workflow.definition,
        changelog=req.changelog,
        created_by=current_user_id(),
    )
    session.add(version)

    # Update workflow
    workflow.status = WorkflowStatus.PUBLISHED
    workflow.version += 1
    workflow.published_at = datetime.utcnow()

    await session.commit()
    await session.refresh(workflow)
    return workflow


@router.post("/{workflow_id}/execute", response_model=ExecutionResult)
async def execute_workflow(
    workflow_id: UUID,
    req: WorkflowExecuteRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    workflow = await _get_tenant_workflow(session, workflow_id)

    if workflow.status != WorkflowStatus.PUBLISHED:
        raise HTTPException(status_code=400, detail="Only published workflows can be executed")

    # Create execution record
    execution = WorkflowExecution(
        workflow_id=workflow.id,
        workflow_version=workflow.version - 1,  # Current published version
        tenant_id=workflow.tenant_id,
        input_data=req.input_data,
        created_by=current_user_id(),
    )
    session.add(execution)
    await session.commit()
    await session.refresh(execution)

    if req.async_mode:
        # Execute in background
        background_tasks.add_task(engine.execute, str(execution.id), workflow, req.input_data, True)
        return ExecutionResult(
            execution_id=execution.id,
            status="started",
        )
    else:
        # Execute synchronously
        result = await engine.execute(str(execution.id), workflow, req.input_data, False)
        return ExecutionResult(
            execution_id=execution.id,
            **result,
        )


# Version routes
@version_router.get("/{workflow_id}", response_model=List[WorkflowVersionRead])
async def list_versions(
    workflow_id: UUID,
    session: AsyncSession = Depends(get_session),
    skip: int = 0,
    limit: int = 20,
):
    workflow = await session.get(Workflow, workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    stmt = select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow_id).order_by(WorkflowVersion.version.desc()).offset(skip).limit(limit)
    result = await session.execute(stmt)
    return result.scalars().all()


@version_router.get("/{workflow_id}/{version}", response_model=WorkflowVersionRead)
async def get_version(workflow_id: UUID, version: int, session: AsyncSession = Depends(get_session)):
    stmt = select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow_id, WorkflowVersion.version == version)
    result = await session.execute(stmt)
    v = result.scalar_one_or_none()
    if not v:
        raise HTTPException(status_code=404, detail="Version not found")
    return v


# Execution routes
@execution_router.get("", response_model=List[WorkflowExecutionRead])
async def list_executions(
    response: Response,
    session: AsyncSession = Depends(get_session),
    workflow_id: Optional[UUID] = None,
    status_filter: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
):
    tenant_id = current_tenant_id()
    stmt = select(WorkflowExecution).where(WorkflowExecution.tenant_id == tenant_id)
    count_stmt = select(func.count(WorkflowExecution.id)).where(
        WorkflowExecution.tenant_id == tenant_id
    )

    if workflow_id:
        stmt = stmt.where(WorkflowExecution.workflow_id == workflow_id)
        count_stmt = count_stmt.where(WorkflowExecution.workflow_id == workflow_id)
    if status_filter:
        stmt = stmt.where(WorkflowExecution.status == status_filter)
        count_stmt = count_stmt.where(WorkflowExecution.status == status_filter)

    stmt = stmt.order_by(WorkflowExecution.created_at.desc()).offset(skip).limit(limit)
    result = await session.execute(stmt)
    response.headers["X-Total-Count"] = str((await session.execute(count_stmt)).scalar() or 0)
    return result.scalars().all()


@execution_router.get("/{execution_id}", response_model=WorkflowExecutionRead)
async def get_execution(execution_id: UUID, session: AsyncSession = Depends(get_session)):
    stmt = select(WorkflowExecution).where(
        WorkflowExecution.id == execution_id,
        WorkflowExecution.tenant_id == current_tenant_id(),
    )
    execution = (await session.execute(stmt)).scalar_one_or_none()
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")
    return execution


@execution_router.get("/{execution_id}/logs", response_model=List[WorkflowExecutionLogRead])
async def get_execution_logs(
    execution_id: UUID,
    session: AsyncSession = Depends(get_session),
    skip: int = 0,
    limit: int = 200,
):
    execution = await session.get(WorkflowExecution, execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")

    stmt = select(WorkflowExecutionLog).where(WorkflowExecutionLog.execution_id == execution_id).order_by(WorkflowExecutionLog.created_at).offset(skip).limit(limit)
    result = await session.execute(stmt)
    return result.scalars().all()


@execution_router.post("/{execution_id}/cancel", response_model=ExecutionResult)
async def cancel_execution(
    execution_id: UUID,
    req: WorkflowCancelRequest,
    session: AsyncSession = Depends(get_session),
):
    execution = await session.get(WorkflowExecution, execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="Execution not found")

    if execution.status not in [ExecutionStatus.PENDING, ExecutionStatus.RUNNING]:
        raise HTTPException(status_code=400, detail="Execution cannot be cancelled")

    await engine.cancel_execution(str(execution_id), req.reason)

    return ExecutionResult(
        execution_id=execution_id,
        status="cancelled",
    )


# Node Template routes
@template_router.post("", response_model=NodeTemplateRead, status_code=status.HTTP_201_CREATED)
async def create_node_template(
    template_in: NodeTemplateCreate,
    session: AsyncSession = Depends(get_session),
):
    tenant_id = current_tenant_id()

    template = NodeTemplate(
        tenant_id=tenant_id,
        **template_in.model_dump(),
    )
    session.add(template)
    await session.commit()
    await session.refresh(template)
    return template


@template_router.get("", response_model=List[NodeTemplateRead])
async def list_node_templates(
    session: AsyncSession = Depends(get_session),
    node_type: Optional[str] = None,
    category: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
):
    tenant_id = current_tenant_id()
    stmt = select(NodeTemplate).where(NodeTemplate.tenant_id == tenant_id)

    if node_type:
        stmt = stmt.where(NodeTemplate.node_type == node_type)
    if category:
        stmt = stmt.where(NodeTemplate.category == category)

    stmt = stmt.order_by(NodeTemplate.category, NodeTemplate.name).offset(skip).limit(limit)
    result = await session.execute(stmt)
    return result.scalars().all()


@template_router.get("/{template_id}", response_model=NodeTemplateRead)
async def get_node_template(template_id: UUID, session: AsyncSession = Depends(get_session)):
    template = await session.get(NodeTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Node template not found")
    return template


# Definition validation
@router.post("/validate", response_model=dict)
async def validate_definition(definition: WorkflowDefinition):
    """Validate workflow definition (nodes, edges, cycles)."""
    errors = []
    warnings = []

    nodes = definition.nodes
    edges = definition.edges

    if not nodes:
        errors.append("Workflow must have at least one node")

    # Check for start node
    start_nodes = [n for n in nodes if n.type == "start"]
    if len(start_nodes) == 0:
        errors.append("Workflow must have a start node")
    elif len(start_nodes) > 1:
        warnings.append("Multiple start nodes found, only first will be used")

    # Check for end node
    end_nodes = [n for n in nodes if n.type == "end"]
    if len(end_nodes) == 0:
        warnings.append("No end node found, workflow may not terminate properly")

    # Check for orphan nodes (not connected)
    connected_nodes = set()
    for edge in edges:
        connected_nodes.add(edge.source)
        connected_nodes.add(edge.target)

    orphan_nodes = [n for n in nodes if n.id not in connected_nodes and n.type not in ["start", "end"]]
    if orphan_nodes:
        warnings.append(f"{len(orphan_nodes)} orphan nodes not connected to any edge")

    # Check for cycles using DFS
    adj = {n.id: [] for n in nodes}
    for edge in edges:
        if edge.source in adj and edge.target in adj:
            adj[edge.source].append(edge.target)

    visited = set()
    rec_stack = set()
    cycles = []

    def dfs(node_id, path):
        visited.add(node_id)
        rec_stack.add(node_id)
        path.append(node_id)

        for neighbor in adj.get(node_id, []):
            if neighbor not in visited:
                dfs(neighbor, path.copy())
            elif neighbor in rec_stack:
                # Found cycle
                cycle_start = path.index(neighbor)
                cycles.append(path[cycle_start:] + [neighbor])

        rec_stack.remove(node_id)

    # 必须遍历节点 id：之前遍历的是 NodeDefinition 对象，set.add 会抛
    # TypeError: unhashable type，任何非空图都会 500（旧冒烟传空图没触发）。
    for node_id in list(adj):
        if node_id not in visited:
            dfs(node_id, [])

    if cycles:
        for cycle in cycles:
            errors.append(f"Cycle detected: {' -> '.join(cycle)}")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "node_count": len(nodes),
        "edge_count": len(edges),
    }


from datetime import datetime