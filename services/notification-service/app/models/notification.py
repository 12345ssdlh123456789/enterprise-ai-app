"""Notification Service notification model（与网关的通知契约对齐）。

字段对齐网关 `app/models/__init__.py::Notification`：`id` / `tenant_id` / `user_id` 都是 UUID，
`title` / `content` / `data` / `read` / `sent_at` 同名同义。这样网关转发时**不需要伪造 ID**
（第 16 轮 `docs/architecture/service-split.md` §5.1 记的就是这个卡点）。

`recipient_id` / `recipient_type` / `status` 是服务侧多出来的投递信息（邮件地址、webhook URL、
投递状态），网关不暴露，但邮件/webhook 渠道还要用。
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid, nullable=True, index=True)
    # 收件人（站内通知）：网关的 user_id
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid, nullable=True, index=True)
    type: Mapped[str] = mapped_column(String(50), default="INFO", nullable=False)
    channel: Mapped[str] = mapped_column(String(50), default="IN_APP", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    # 外部收件人（email / webhook / slack）：可能不是 UUID，网关不暴露
    recipient_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    recipient_type: Mapped[str] = mapped_column(String(50), default="user", nullable=False)
    # 投递状态：pending / sent / failed / read
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
