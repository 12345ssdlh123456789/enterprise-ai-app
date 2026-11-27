"""审计写入服务。

审计表是只读、追加写的；这里只提供创建入口，不提供修改/删除。
调用方负责在业务事务里调用 `record_audit(...)`，由它 `flush()`，
最后和业务数据一起 `commit()`；失败事件（如登录失败）用 `commit=True`
立即落库，保证即使随后抛 HTTPException 也留痕。
"""

from typing import Any, Optional
from uuid import UUID

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditAction, AuditLog


def jsonable(value: Any) -> Any:
    """把枚举 / UUID 等转成可写进 JSON 列的值。"""
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def _client_ip(request: Optional[Request]) -> Optional[str]:
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45]
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()[:45]
    return request.client.host[:45] if request.client else None


def _user_agent(request: Optional[Request]) -> Optional[str]:
    if request is None:
        return None
    ua = request.headers.get("user-agent")
    return ua[:500] if ua else None


async def record_audit(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    action: AuditAction | str,
    resource: str,
    user_id: Optional[UUID] = None,
    resource_id: Optional[UUID] = None,
    old_value: Optional[dict[str, Any]] = None,
    new_value: Optional[dict[str, Any]] = None,
    request: Optional[Request] = None,
    success: bool = True,
    error_message: Optional[str] = None,
    commit: bool = False,
) -> AuditLog:
    """写一条审计日志。

    - `resource` 是资源类型（user / model / tenant / auth …）；
    - 非 UUID 主键（例如模型 ID `gpt-4o`）不要塞进 `resource_id`，
      放进 `new_value` 里；
    - `commit=False` 时只 flush，由调用方统一提交。
    """
    log = AuditLog(
        tenant_id=tenant_id,
        user_id=user_id,
        action=AuditAction(action) if isinstance(action, str) else action,
        resource=resource,
        resource_id=resource_id,
        old_value=old_value,
        new_value=new_value,
        ip_address=_client_ip(request),
        user_agent=_user_agent(request),
        success=success,
        error_message=error_message,
    )
    db.add(log)

    if commit:
        await db.commit()
    else:
        await db.flush()

    return log
