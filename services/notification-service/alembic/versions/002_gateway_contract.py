"""Align notifications with the gateway contract（UUID 主键 + user_id / title / data / read）

Revision ID: 002_gateway_contract
Revises: 001_initial_schema

旧表是 `int` 主键 + `recipient_id` / `subject` / `status`，网关的 `UUID` / `user_id` /
`title` / `read` 一个都对不上；假造 UUID 会让「已读 / 删除」按 ID 找不到记录
（`docs/architecture/service-split.md` §5.1 记的就是这个卡点）。

这里把表重建成网关契约：
- `id` 改成 UUID（**行 ID 会变**，旧 ID 是自增整数，无法无损映射）；
- `recipient_id` 本身是合法 UUID 的行，同时写入 `user_id`；非 UUID 的外部收件人
  （邮箱、webhook URL）保留在 `recipient_id`，`user_id` 为 NULL；
- `subject` → `title`（为空时取正文首行），`status == "read"` → `read = true`；
- 其它投递字段（`recipient_type` / `status` / `sent_at` / `read_at`）原样保留。

做法是「先建新表 → 拷数据 → 删旧表 → 改名」：SQLite 的 DDL 不是事务性的，
直接在原表上 drop/create，一旦拷贝失败数据就没了。数据保留，但 downgrade 只能恢复旧表结构、
无法恢复原来的整数 ID。
"""

import uuid
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "002_gateway_contract"
down_revision = "001_initial_schema"
branch_labels = None
depends_on = None

_CHANNELS = {"IN_APP", "EMAIL", "WEBHOOK", "SLACK", "DINGTALK", "FEISHU"}


def _as_uuid(value):
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _as_datetime(value, *, required: bool = False):
    """裸 SQL 读出来的时间是字符串，`sa.DateTime` 只接受 datetime，这里统一转换。"""
    if isinstance(value, datetime):
        return value
    if value is None:
        return datetime.utcnow() if required else None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return datetime.utcnow() if required else None


def _channel(raw):
    value = (raw or "").upper()
    return value if value in _CHANNELS else "IN_APP"


def _new_table(name: str = "notifications_new") -> sa.TableClause:
    return sa.table(
        name,
        sa.column("id", sa.Uuid()),
        sa.column("tenant_id", sa.Uuid()),
        sa.column("user_id", sa.Uuid()),
        sa.column("type", sa.String()),
        sa.column("channel", sa.String()),
        sa.column("title", sa.String()),
        sa.column("content", sa.Text()),
        sa.column("data", sa.JSON()),
        sa.column("read", sa.Boolean()),
        sa.column("recipient_id", sa.String()),
        sa.column("recipient_type", sa.String()),
        sa.column("status", sa.String()),
        sa.column("created_at", sa.DateTime()),
        sa.column("sent_at", sa.DateTime()),
        sa.column("read_at", sa.DateTime()),
    )


def upgrade() -> None:
    bind = op.get_bind()
    rows = (
        bind.execute(
            sa.text(
                "SELECT recipient_id, recipient_type, channel, subject, content, status, "
                "tenant_id, created_at, sent_at, read_at FROM notifications"
            )
        )
        .mappings()
        .all()
    )

    op.create_table(
        "notifications_new",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("type", sa.String(length=50), nullable=False, server_default="INFO"),
        sa.Column("channel", sa.String(length=50), nullable=False, server_default="IN_APP"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("read", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("recipient_id", sa.String(length=100), nullable=True),
        sa.Column("recipient_type", sa.String(length=50), nullable=False, server_default="user"),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    if rows:
        payload = []
        for row in rows:
            recipient = row["recipient_id"]
            content = row["content"] or ""
            first_line = content.strip().splitlines()[0] if content.strip() else ""
            title = (row["subject"] or first_line or "通知")[:255]
            payload.append(
                {
                    "id": uuid.uuid4(),
                    "tenant_id": _as_uuid(row["tenant_id"]),
                    "user_id": _as_uuid(recipient),
                    "type": "INFO",
                    "channel": _channel(row["channel"]),
                    "title": title,
                    "content": content,
                    "data": None,
                    "read": (row["status"] or "") == "read",
                    "recipient_id": recipient,
                    "recipient_type": row["recipient_type"] or "user",
                    "status": row["status"] or "pending",
                    "created_at": _as_datetime(row["created_at"], required=True),
                    "sent_at": _as_datetime(row["sent_at"]),
                    "read_at": _as_datetime(row["read_at"]),
                }
            )
        op.bulk_insert(_new_table(), payload)

    op.drop_table("notifications")
    op.rename_table("notifications_new", "notifications")

    for name, columns in (
        ("ix_notifications_tenant_id", ["tenant_id"]),
        ("ix_notifications_user_id", ["user_id"]),
        ("ix_notifications_read", ["read"]),
        ("ix_notifications_created_at", ["created_at"]),
        ("ix_notifications_recipient_id", ["recipient_id"]),
    ):
        op.create_index(name, "notifications", columns, unique=False)


def downgrade() -> None:
    """回到旧结构（int 主键 + subject）。旧行无法映射回整数 ID，所以这里只重建空表。"""
    op.drop_index(op.f("ix_notifications_recipient_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_created_at"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_read"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_user_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_tenant_id"), table_name="notifications")
    op.drop_table("notifications")
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("recipient_id", sa.String(length=100), nullable=False),
        sa.Column("recipient_type", sa.String(length=50), nullable=False, server_default="user"),
        sa.Column("channel", sa.String(length=50), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("tenant_id", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_notifications_id"), "notifications", ["id"], unique=False)
    op.create_index(
        op.f("ix_notifications_recipient_id"), "notifications", ["recipient_id"], unique=False
    )
    op.create_index(op.f("ix_notifications_tenant_id"), "notifications", ["tenant_id"], unique=False)
