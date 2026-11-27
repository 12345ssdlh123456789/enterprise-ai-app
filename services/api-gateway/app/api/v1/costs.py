# API Gateway - Costs Routes

from typing import Optional
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import get_current_user, get_current_tenant, get_role_permissions, has_permission
from app.db.session import get_async_db
from app.models import CostRecord, TokenBudget, User, Tenant
from app.schemas import (
    CostRecordSchema,
    TokenBudgetSchema,
    PaginationParams,
    PaginatedResponse,
    ApiResponse,
    ResponseMeta,
)

router = APIRouter(prefix="/costs", tags=["Costs"])


def create_meta(request: Request) -> ResponseMeta:
    return ResponseMeta(
        request_id=getattr(request.state, "request_id", "unknown"),
        timestamp=datetime.now(timezone.utc),
        version=settings.APP_VERSION,
    )


def _iso_date(value) -> Optional[str]:
    """`func.date()` 在 SQLite 返回字符串、在 PostgreSQL 返回 date，统一成 ISO 字符串。"""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def cost_to_schema(cost: CostRecord) -> CostRecordSchema:
    return CostRecordSchema(
        id=cost.id,
        tenant_id=cost.tenant_id,
        user_id=cost.user_id,
        model_id=cost.model_id,
        model_provider=cost.model_provider.value,
        operation_type=cost.operation_type,
        prompt_tokens=cost.prompt_tokens,
        completion_tokens=cost.completion_tokens,
        total_tokens=cost.total_tokens,
        estimated_cost=float(cost.estimated_cost),
        currency=cost.currency,
        metadata=cost.meta,
        created_at=cost.created_at,
    )


# ============================================
# 获取成本记录
# ============================================

@router.get("/records", response_model=ApiResponse[PaginatedResponse[CostRecordSchema]])
async def list_cost_records(
    request: Request,
    pagination: PaginationParams = Depends(),
    model_id: Optional[str] = Query(None, description="按模型筛选"),
    operation_type: Optional[str] = Query(None, description="按操作类型筛选"),
    start_date: Optional[datetime] = Query(None, description="开始日期"),
    end_date: Optional[datetime] = Query(None, description="结束日期"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """获取成本记录"""
    user_perms = get_role_permissions(current_user.role.value)
    if not has_permission(user_perms, "analytics:read") and current_user.role.value not in ["SUPER_ADMIN", "ADMIN"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: requires admin",
        )

    query = select(CostRecord).where(CostRecord.tenant_id == current_tenant.id)
    count_query = select(func.count(CostRecord.id)).where(CostRecord.tenant_id == current_tenant.id)

    # 非管理员只能看自己的
    if current_user.role.value not in ["SUPER_ADMIN", "ADMIN"]:
        query = query.where(CostRecord.user_id == current_user.id)
        count_query = count_query.where(CostRecord.user_id == current_user.id)

    if model_id:
        query = query.where(CostRecord.model_id == model_id)
        count_query = count_query.where(CostRecord.model_id == model_id)

    if operation_type:
        query = query.where(CostRecord.operation_type == operation_type)
        count_query = count_query.where(CostRecord.operation_type == operation_type)

    if start_date:
        query = query.where(CostRecord.created_at >= start_date)
        count_query = count_query.where(CostRecord.created_at >= start_date)

    if end_date:
        query = query.where(CostRecord.created_at <= end_date)
        count_query = count_query.where(CostRecord.created_at <= end_date)

    query = query.order_by(desc(CostRecord.created_at))
    offset = (pagination.page - 1) * pagination.page_size
    query = query.offset(offset).limit(pagination.page_size)

    result = await db.execute(query)
    costs = result.scalars().all()

    count_result = await db.execute(count_query)
    total = count_result.scalar()

    items = [cost_to_schema(c) for c in costs]
    paginated = PaginatedResponse.create(items, total, pagination)

    return ApiResponse(data=paginated, meta=create_meta(request))


# ============================================
# 获取成本汇总
# ============================================

@router.get("/summary", response_model=ApiResponse)
async def get_cost_summary(
    request: Request,
    period: str = Query("monthly", pattern="^(daily|weekly|monthly)$"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """获取成本汇总统计"""
    user_perms = get_role_permissions(current_user.role.value)
    if not has_permission(user_perms, "analytics:read") and current_user.role.value not in ["SUPER_ADMIN", "ADMIN"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: requires admin",
        )

    # 计算时间范围
    now = datetime.now()
    if period == "daily":
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "weekly":
        start_date = now - timedelta(days=now.weekday())
        start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
    else:  # monthly
        start_date = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # 总成本
    total_result = await db.execute(
        select(
            func.sum(CostRecord.estimated_cost).label("total_cost"),
            func.sum(CostRecord.total_tokens).label("total_tokens"),
            func.count(CostRecord.id).label("total_requests"),
        ).where(
            CostRecord.tenant_id == current_tenant.id,
            CostRecord.created_at >= start_date,
        )
    )
    total_row = total_result.first()

    # 按模型分组
    model_result = await db.execute(
        select(
            CostRecord.model_id,
            func.sum(CostRecord.estimated_cost).label("cost"),
            func.sum(CostRecord.total_tokens).label("tokens"),
            func.count(CostRecord.id).label("requests"),
        ).where(
            CostRecord.tenant_id == current_tenant.id,
            CostRecord.created_at >= start_date,
        ).group_by(CostRecord.model_id)
    )
    by_model = [
        {
            "model_id": row.model_id,
            "cost": float(row.cost or 0),
            "tokens": row.tokens or 0,
            "requests": row.requests or 0,
        }
        for row in model_result
    ]

    # 按操作类型分组
    op_result = await db.execute(
        select(
            CostRecord.operation_type,
            func.sum(CostRecord.estimated_cost).label("cost"),
            func.sum(CostRecord.total_tokens).label("tokens"),
        ).where(
            CostRecord.tenant_id == current_tenant.id,
            CostRecord.created_at >= start_date,
        ).group_by(CostRecord.operation_type)
    )
    by_operation = [
        {
            "operation_type": row.operation_type,
            "cost": float(row.cost or 0),
            "tokens": row.tokens or 0,
        }
        for row in op_result
    ]

    # 按日期分组 (用于图表)
    daily_result = await db.execute(
        select(
            func.date(CostRecord.created_at).label("date"),
            func.sum(CostRecord.estimated_cost).label("cost"),
            func.sum(CostRecord.total_tokens).label("tokens"),
        ).where(
            CostRecord.tenant_id == current_tenant.id,
            CostRecord.created_at >= start_date,
        ).group_by(func.date(CostRecord.created_at)).order_by(func.date(CostRecord.created_at))
    )
    by_date = [
        {
            # SQLite 的 func.date() 返回字符串，PostgreSQL 返回 date 对象，两种都要能序列化
            "date": _iso_date(row.date),
            "cost": float(row.cost or 0),
            "tokens": row.tokens or 0,
        }
        for row in daily_result
    ]

    return ApiResponse(data={
        "period": period,
        "start_date": start_date.isoformat(),
        "end_date": now.isoformat(),
        "total_cost": float(total_row.total_cost or 0),
        "total_tokens": total_row.total_tokens or 0,
        "total_requests": total_row.total_requests or 0,
        "by_model": by_model,
        "by_operation": by_operation,
        "by_date": by_date,
    }, meta=create_meta(request))


# ============================================
# 获取 Token 预算
# ============================================

@router.get("/budget", response_model=ApiResponse[TokenBudgetSchema])
async def get_token_budget(
    request: Request,
    period: str = Query("monthly", pattern="^(daily|monthly)$"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    current_tenant: Tenant = Depends(get_current_tenant),
):
    """获取 Token 预算使用情况"""
    user_perms = get_role_permissions(current_user.role.value)
    if not has_permission(user_perms, "analytics:read") and current_user.role.value not in ["SUPER_ADMIN", "ADMIN"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: requires admin",
        )

    result = await db.execute(
        select(TokenBudget).where(
            TokenBudget.tenant_id == current_tenant.id,
            TokenBudget.period == period,
        )
    )
    budget = result.scalar_one_or_none()

    if not budget:
        # 返回默认预算
        default_limit = current_tenant.settings.get("maxTokenBudgetMonthly", 1000000)
        if period == "daily":
            default_limit = default_limit // 30

        return ApiResponse(data=TokenBudgetSchema(
            tenant_id=current_tenant.id,
            period=period,
            limit=default_limit,
            used=0,
            reset_at=datetime.now() + timedelta(days=1 if period == "daily" else 30),
            usage_percentage=0.0,
        ), meta=create_meta(request))

    usage_percentage = (budget.used / budget.limit * 100) if budget.limit > 0 else 0

    return ApiResponse(data=TokenBudgetSchema(
        tenant_id=budget.tenant_id,
        period=budget.period,
        limit=budget.limit,
        used=budget.used,
        reset_at=budget.reset_at,
        usage_percentage=round(usage_percentage, 2),
    ), meta=create_meta(request))
