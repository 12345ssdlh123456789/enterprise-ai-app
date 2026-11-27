import time
import uuid
from abc import ABC, abstractmethod
from typing import AsyncGenerator, List, Dict, Any
from dataclasses import dataclass
from enum import Enum

import httpx
import tiktoken
from openai import AsyncOpenAI, AsyncAzureOpenAI
from anthropic import AsyncAnthropic

from app.core.config import settings
from app.core.logging import setup_logging
from app.models import ProviderConfig, ModelConfig, ProviderType, ProviderStatus

setup_logging()
import structlog
logger = structlog.get_logger()


@dataclass
class ProviderEndpoint:
    provider: ProviderConfig
    model: ModelConfig
    client: Any
    healthy: bool = True
    consecutive_failures: int = 0
    last_failure_time: float = 0


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(self, failure_threshold: int, recovery_timeout: int, half_open_requests: int):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_requests = half_open_requests
        self.state = CircuitState.CLOSED
        self.failures = 0
        self.successes = 0
        self.last_failure_time = 0
        self.half_open_successes = 0

    def record_success(self):
        if self.state == CircuitState.HALF_OPEN:
            self.half_open_successes += 1
            if self.half_open_successes >= self.half_open_requests:
                self.state = CircuitState.CLOSED
                self.failures = 0
                self.half_open_successes = 0
        elif self.state == CircuitState.CLOSED:
            self.failures = 0

    def record_failure(self):
        self.failures += 1
        self.last_failure_time = time.time()
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
            self.half_open_successes = 0
        elif self.state == CircuitState.CLOSED and self.failures >= self.failure_threshold:
            self.state = CircuitState.OPEN

    def can_execute(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time >= self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                self.half_open_successes = 0
                return True
            return False
        return True  # HALF_OPEN


class BaseProvider(ABC):
    def __init__(self, provider: ProviderConfig, model: ModelConfig):
        self.provider = provider
        self.model = model
        self.circuit_breaker = CircuitBreaker(
            settings.CB_FAILURE_THRESHOLD,
            settings.CB_RECOVERY_TIMEOUT,
            settings.CB_HALF_OPEN_REQUESTS,
        )

    @abstractmethod
    async def chat_completion(self, request: Dict[str, Any]) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def stream_chat_completion(self, request: Dict[str, Any]) -> AsyncGenerator[Dict[str, Any], None]:
        pass

    @abstractmethod
    async def embeddings(self, request: Dict[str, Any]) -> Dict[str, Any]:
        pass

    def is_healthy(self) -> bool:
        return self.circuit_breaker.can_execute() and self.provider.status == ProviderStatus.ACTIVE


class OpenAIProvider(BaseProvider):
    def __init__(self, provider: ProviderConfig, model: ModelConfig):
        super().__init__(provider, model)
        self.client = AsyncOpenAI(
            api_key=provider.api_key,
            base_url=provider.api_base,
            timeout=provider.timeout_seconds,
            max_retries=provider.max_retries,
        )

    async def chat_completion(self, request: Dict[str, Any]) -> Dict[str, Any]:
        if not self.circuit_breaker.can_execute():
            raise Exception("Circuit breaker open")

        start = time.perf_counter()
        try:
            response = await self.client.chat.completions.create(
                model=self.model.name,
                messages=request["messages"],
                temperature=request.get("temperature", 1.0),
                top_p=request.get("top_p", 1.0),
                n=request.get("n", 1),
                stream=False,
                max_tokens=request.get("max_tokens"),
                presence_penalty=request.get("presence_penalty", 0.0),
                frequency_penalty=request.get("frequency_penalty", 0.0),
                tools=request.get("tools"),
                tool_choice=request.get("tool_choice"),
                response_format=request.get("response_format"),
                user=request.get("user"),
            )
            latency_ms = int((time.perf_counter() - start) * 1000)
            self.circuit_breaker.record_success()
            return {
                "response": response.model_dump(),
                "latency_ms": latency_ms,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens,
                },
            }
        except Exception:
            self.circuit_breaker.record_failure()
            latency_ms = int((time.perf_counter() - start) * 1000)
            raise

    async def stream_chat_completion(self, request: Dict[str, Any]) -> AsyncGenerator[Dict[str, Any], None]:
        if not self.circuit_breaker.can_execute():
            raise Exception("Circuit breaker open")

        stream = await self.client.chat.completions.create(
            model=self.model.name,
            messages=request["messages"],
            temperature=request.get("temperature", 1.0),
            top_p=request.get("top_p", 1.0),
            n=request.get("n", 1),
            stream=True,
            max_tokens=request.get("max_tokens"),
            presence_penalty=request.get("presence_penalty", 0.0),
            frequency_penalty=request.get("frequency_penalty", 0.0),
            tools=request.get("tools"),
            tool_choice=request.get("tool_choice"),
            response_format=request.get("response_format"),
            user=request.get("user"),
        )

        self.circuit_breaker.record_success()
        async for chunk in stream:
            yield chunk.model_dump()

    async def embeddings(self, request: Dict[str, Any]) -> Dict[str, Any]:
        if not self.circuit_breaker.can_execute():
            raise Exception("Circuit breaker open")

        start = time.perf_counter()
        try:
            response = await self.client.embeddings.create(
                model=self.model.name,
                input=request["input"],
                encoding_format=request.get("encoding_format", "float"),
                dimensions=request.get("dimensions"),
                user=request.get("user"),
            )
            latency_ms = int((time.perf_counter() - start) * 1000)
            self.circuit_breaker.record_success()
            return {
                "response": response.model_dump(),
                "latency_ms": latency_ms,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "total_tokens": response.usage.total_tokens,
                },
            }
        except Exception:
            self.circuit_breaker.record_failure()
            latency_ms = int((time.perf_counter() - start) * 1000)
            raise


class AnthropicProvider(BaseProvider):
    def __init__(self, provider: ProviderConfig, model: ModelConfig):
        super().__init__(provider, model)
        self.client = AsyncAnthropic(
            api_key=provider.api_key,
            base_url=provider.api_base,
            timeout=provider.timeout_seconds,
            max_retries=provider.max_retries,
        )

    def _convert_messages(self, messages: List[Dict]) -> tuple:
        system = None
        converted = []
        for msg in messages:
            if msg["role"] == "system":
                system = msg["content"]
            else:
                converted.append({"role": msg["role"], "content": msg["content"]})
        return system, converted

    async def chat_completion(self, request: Dict[str, Any]) -> Dict[str, Any]:
        if not self.circuit_breaker.can_execute():
            raise Exception("Circuit breaker open")

        start = time.perf_counter()
        try:
            system, messages = self._convert_messages(request["messages"])
            response = await self.client.messages.create(
                model=self.model.name,
                messages=messages,
                system=system,
                max_tokens=request.get("max_tokens", self.model.max_output_tokens),
                temperature=request.get("temperature", 1.0),
                top_p=request.get("top_p", 1.0),
                stream=False,
            )
            latency_ms = int((time.perf_counter() - start) * 1000)
            self.circuit_breaker.record_success()

            # Convert to OpenAI format
            return {
                "response": {
                    "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": self.model.name,
                    "choices": [{
                        "index": 0,
                        "message": {"role": "assistant", "content": response.content[0].text},
                        "finish_reason": "stop" if response.stop_reason == "end_turn" else "length",
                    }],
                    "usage": {
                        "prompt_tokens": response.usage.input_tokens,
                        "completion_tokens": response.usage.output_tokens,
                        "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
                    },
                },
                "latency_ms": latency_ms,
                "usage": {
                    "prompt_tokens": response.usage.input_tokens,
                    "completion_tokens": response.usage.output_tokens,
                    "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
                },
            }
        except Exception:
            self.circuit_breaker.record_failure()
            latency_ms = int((time.perf_counter() - start) * 1000)
            raise

    async def stream_chat_completion(self, request: Dict[str, Any]) -> AsyncGenerator[Dict[str, Any], None]:
        if not self.circuit_breaker.can_execute():
            raise Exception("Circuit breaker open")

        system, messages = self._convert_messages(request["messages"])
        stream = await self.client.messages.create(
            model=self.model.name,
            messages=messages,
            system=system,
            max_tokens=request.get("max_tokens", self.model.max_output_tokens),
            temperature=request.get("temperature", 1.0),
            top_p=request.get("top_p", 1.0),
            stream=True,
        )

        self.circuit_breaker.record_success()
        async for chunk in stream:
            if chunk.type == "content_block_delta":
                yield {
                    "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": self.model.name,
                    "choices": [{
                        "index": 0,
                        "delta": {"role": "assistant", "content": chunk.delta.text},
                        "finish_reason": None,
                    }],
                }
            elif chunk.type == "message_stop":
                yield {
                    "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": self.model.name,
                    "choices": [{
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop",
                    }],
                }

    async def embeddings(self, request: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError("Anthropic doesn't support embeddings")


class AzureOpenAIProvider(OpenAIProvider):
    def __init__(self, provider: ProviderConfig, model: ModelConfig):
        super().__init__(provider, model)
        self.client = AsyncAzureOpenAI(
            api_key=provider.api_key,
            azure_endpoint=provider.api_base,
            api_version=provider.api_version or settings.AZURE_OPENAI_API_VERSION,
            timeout=provider.timeout_seconds,
            max_retries=provider.max_retries,
        )


class OllamaProvider(BaseProvider):
    def __init__(self, provider: ProviderConfig, model: ModelConfig):
        super().__init__(provider, model)
        self.base_url = provider.api_base or settings.OLLAMA_BASE_URL
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=provider.timeout_seconds,
        )

    async def chat_completion(self, request: Dict[str, Any]) -> Dict[str, Any]:
        if not self.circuit_breaker.can_execute():
            raise Exception("Circuit breaker open")

        start = time.perf_counter()
        try:
            payload = {
                "model": self.model.name,
                "messages": request["messages"],
                "stream": False,
                "options": {
                    "temperature": request.get("temperature", 1.0),
                    "top_p": request.get("top_p", 1.0),
                    "num_predict": request.get("max_tokens", self.model.max_output_tokens),
                },
            }
            response = await self.client.post("/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()

            latency_ms = int((time.perf_counter() - start) * 1000)
            self.circuit_breaker.record_success()

            # Estimate tokens
            encoding = tiktoken.get_encoding("cl100k_base")
            prompt_tokens = sum(len(encoding.encode(m["content"])) for m in request["messages"])
            completion_tokens = len(encoding.encode(data.get("message", {}).get("content", "")))

            return {
                "response": {
                    "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": self.model.name,
                    "choices": [{
                        "index": 0,
                        "message": {"role": "assistant", "content": data.get("message", {}).get("content", "")},
                        "finish_reason": "stop" if data.get("done") else "length",
                    }],
                    "usage": {
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": prompt_tokens + completion_tokens,
                    },
                },
                "latency_ms": latency_ms,
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                },
            }
        except Exception:
            self.circuit_breaker.record_failure()
            latency_ms = int((time.perf_counter() - start) * 1000)
            raise

    async def stream_chat_completion(self, request: Dict[str, Any]) -> AsyncGenerator[Dict[str, Any], None]:
        if not self.circuit_breaker.can_execute():
            raise Exception("Circuit breaker open")

        payload = {
            "model": self.model.name,
            "messages": request["messages"],
            "stream": True,
            "options": {
                "temperature": request.get("temperature", 1.0),
                "top_p": request.get("top_p", 1.0),
                "num_predict": request.get("max_tokens", self.model.max_output_tokens),
            },
        }

        self.circuit_breaker.record_success()
        async with self.client.stream("POST", "/api/chat", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line:
                    import json
                    data = json.loads(line)
                    if data.get("message", {}).get("content"):
                        yield {
                            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": self.model.name,
                            "choices": [{
                                "index": 0,
                                "delta": {"role": "assistant", "content": data["message"]["content"]},
                                "finish_reason": None,
                            }],
                        }
                    if data.get("done"):
                        yield {
                            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": self.model.name,
                            "choices": [{
                                "index": 0,
                                "delta": {},
                                "finish_reason": "stop",
                            }],
                        }

    async def embeddings(self, request: Dict[str, Any]) -> Dict[str, Any]:
        if not self.circuit_breaker.can_execute():
            raise Exception("Circuit breaker open")

        start = time.perf_counter()
        try:
            payload = {
                "model": self.model.name,
                "input": request["input"],
            }
            response = await self.client.post("/api/embed", json=payload)
            response.raise_for_status()
            data = response.json()

            latency_ms = int((time.perf_counter() - start) * 1000)
            self.circuit_breaker.record_success()

            embeddings = data.get("embeddings", [])
            prompt_tokens = sum(len(e) for e in embeddings)  # rough estimate

            return {
                "response": {
                    "object": "list",
                    "data": [
                        {"object": "embedding", "index": i, "embedding": emb}
                        for i, emb in enumerate(embeddings)
                    ],
                    "model": self.model.name,
                    "usage": {"prompt_tokens": prompt_tokens, "total_tokens": prompt_tokens},
                },
                "latency_ms": latency_ms,
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "total_tokens": prompt_tokens,
                },
            }
        except Exception:
            self.circuit_breaker.record_failure()
            latency_ms = int((time.perf_counter() - start) * 1000)
            raise


class ProviderFactory:
    _providers: Dict[ProviderType, type] = {
        ProviderType.OPENAI: OpenAIProvider,
        ProviderType.ANTHROPIC: AnthropicProvider,
        ProviderType.AZURE_OPENAI: AzureOpenAIProvider,
        ProviderType.OLLAMA: OllamaProvider,
    }

    @classmethod
    def create(cls, provider: ProviderConfig, model: ModelConfig) -> BaseProvider:
        provider_class = cls._providers.get(provider.provider_type)
        if not provider_class:
            raise ValueError(f"Unknown provider type: {provider.provider_type}")
        return provider_class(provider, model)