"""数据库类型兼容层。

同一套 SQLAlchemy 模型要同时支持两种运行模式：

* PostgreSQL（生产 / docker-compose）：原生 UUID、JSONB、INET；
* SQLite（本地零依赖演示模式，默认）：退化为 CHAR(36)、JSON、VARCHAR。

调用方不需要感知差异，模型里照常写 ``GUID`` / ``JSONType`` / ``InetType``。
"""

import uuid
from typing import Any, Optional

from sqlalchemy import JSON, String
from sqlalchemy.dialects.postgresql import INET as PG_INET
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.engine import Dialect
from sqlalchemy.types import CHAR, TypeDecorator


class GUID(TypeDecorator):
    """跨库 UUID：PostgreSQL 用原生 uuid，SQLite 存 36 位字符串。"""

    impl = CHAR
    cache_ok = True

    def __init__(self, *args: Any, as_uuid: bool = True, **kwargs: Any) -> None:
        self.as_uuid = as_uuid
        super().__init__(*args, **kwargs)

    def load_dialect_impl(self, dialect: Dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value: Any, dialect: Dialect):
        if value is None:
            return None
        if not isinstance(value, uuid.UUID):
            value = uuid.UUID(str(value))
        return value if dialect.name == "postgresql" else str(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> Optional[uuid.UUID]:
        if value is None:
            return None
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


class JSONType(TypeDecorator):
    """跨库 JSON：PostgreSQL 用 JSONB，其它方言用通用 JSON。"""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


class InetType(TypeDecorator):
    """跨库 IP 字段：PostgreSQL 用 INET，其它方言用 VARCHAR(45)。"""

    impl = String(45)
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_INET())
        return dialect.type_descriptor(String(45))
