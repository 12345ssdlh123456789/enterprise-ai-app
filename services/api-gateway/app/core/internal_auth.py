"""网关 → 微服务的内部请求签名（签名方）。

各微服务用 `app/core/service_auth.py` 校验，canonical 规则必须与那边保持一致：

    METHOD \\n PATH \\n tenant \\n user \\n timestamp

⚠️ 两侧的 `SERVICE_API_KEY` 必须相同：网关 `.env` 里的值要和各微服务进程的环境变量一致，
否则微服务会返回 401「签名不匹配」。网关默认值是进程内随机串，只适合单体模式；
一旦要让网关转发到微服务，请在 `.env` 里显式配置同一个密钥。
"""

from __future__ import annotations

import hashlib
import hmac
import time

from app.core.config import settings

MAX_SKEW_SECONDS = 300


def canonical_string(method: str, path: str, tenant_id: str, user_id: str, timestamp) -> str:
    return "\n".join([method.upper(), path, tenant_id or "", user_id or "", str(timestamp)])


def internal_headers(
    method: str,
    path: str,
    tenant_id: str = "",
    user_id: str = "",
    timestamp=None,
) -> dict:
    """返回转发给微服务时该带的头：租户/用户 + 时间戳 + 签名。"""
    key = settings.SERVICE_API_KEY or ""
    if not key:
        raise RuntimeError(
            "SERVICE_API_KEY 未配置：网关无法为内部请求签名，"
            "请在 .env 里设置与微服务一致的密钥（本地可用 dev-internal-key）"
        )

    ts = str(int(timestamp if timestamp is not None else time.time()))
    mac = hmac.new(
        key.encode("utf-8"),
        canonical_string(method, path, tenant_id, user_id, ts).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    headers = {"X-Service-Timestamp": ts, "X-Service-Signature": mac}
    if tenant_id:
        headers["X-Tenant-Id"] = str(tenant_id)
    if user_id:
        headers["X-User-Id"] = str(user_id)
    return headers
