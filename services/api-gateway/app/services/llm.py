"""网关侧的模型调用（对话与工作流共用一份实现）。

项目默认 `LLM_PROVIDER=ollama`，所以这里实现的是 Ollama 的 `/api/chat`（非流式）。
`OPENAI_*` 配置已经存在但还没接 —— 要接的话只改这个文件，调用方（`conversations.py`、
`workflow_runner.py`）不需要动。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """模型调用失败：连不上、非 200、或返回了空内容。"""


@dataclass
class LLMResult:
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


async def chat(
    messages: List[dict],
    *,
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 2048,
    timeout: float = 120.0,
) -> LLMResult:
    """调用 Ollama `/api/chat`（非流式），返回回复文本与 token 用量。"""
    model_name = model or settings.OLLAMA_CHAT_MODEL
    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/chat"
    payload = {
        "model": model_name,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
            resp = await client.post(url, json=payload)
    except httpx.RequestError as exc:
        raise LLMError(f"连不上 {settings.OLLAMA_BASE_URL}：{exc}") from exc

    if resp.status_code >= 400:
        raise LLMError(f"{url} 返回 {resp.status_code}：{resp.text[:200]}")

    try:
        data = resp.json()
    except ValueError as exc:
        raise LLMError(f"{url} 返回的不是 JSON：{resp.text[:200]}") from exc

    content = (data.get("message") or {}).get("content") or ""
    return LLMResult(
        content=content,
        model=data.get("model") or model_name,
        prompt_tokens=int(data.get("prompt_eval_count") or 0),
        completion_tokens=int(data.get("eval_count") or 0),
    )
