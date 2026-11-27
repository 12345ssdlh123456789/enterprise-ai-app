"""Notification Service notification schemas.

对外契约与网关 `/api/v1/notifications` 对齐：UUID 主键、`user_id` 收件人、
`title` / `data` / `read`。旧的 `subject` 仍然接收（等价于 `title`），避免已有调用方直接 422。
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class NotificationCreate(BaseModel):
    # 收件人：不传就是当前请求用户（网关转发时来自 JWT）
    user_id: Optional[UUID] = None
    # 外部收件人（email / webhook）：与 user_id 二选一，站内通知可不传
    recipient_id: Optional[str] = Field(None, max_length=100)
    recipient_type: str = Field("user", max_length=50)

    type: str = Field("INFO", max_length=50)
    channel: str = Field("IN_APP", max_length=50)
    title: Optional[str] = Field(None, max_length=255)
    # 兼容旧调用方：没有 title 时用 subject
    subject: Optional[str] = Field(None, max_length=255)
    content: str = Field(..., min_length=1)
    data: Optional[dict] = None
    tenant_id: Optional[UUID] = None

    def resolved_title(self) -> str:
        title = (self.title or self.subject or "").strip()
        if title:
            return title[:255]
        # 兜底：正文首行，保证 title 非空（网关的 NotificationSchema.title 是必填）
        first_line = (self.content or "").strip().splitlines()[0] if self.content else ""
        return first_line[:255] or "通知"


class NotificationResponse(BaseModel):
    id: UUID
    tenant_id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    type: str
    channel: str
    title: str
    content: str
    data: Optional[dict] = None
    read: bool
    recipient_id: Optional[str] = None
    recipient_type: str
    status: str
    created_at: datetime
    sent_at: Optional[datetime] = None
    read_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class NotificationList(BaseModel):
    items: list[NotificationResponse]
    total: int
