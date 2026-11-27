import time
import random
import uuid
from typing import Optional, List, Dict, Any, AsyncGenerator
from uuid import UUID
from enum import Enum
from dataclasses import dataclass

from sqlalchemy import select

from app.core.config import settings
from app.models import ProviderConfig, ModelConfig, UsageRecord, ModelType, ProviderStatus
from app.db.session import session_context
from app.services.providers import ProviderFactory, BaseProvider

import structlog
logger = structlog.get_logger()


class LoadBalancingStrategy(str, Enum):
    ROUND_ROBIN = "round_robin"
    LEAST_LATENCY = "least_latency"
    COST_AWARE = "cost_aware"
    RANDOM = "random"


@dataclass
class ModelEndpoint:
    provider: ProviderConfig
    model: ModelConfig
    provider_instance: BaseProvider
    weight: float = 1.0
    current_index: int = 0  # for round robin


class LoadBalancer:
    def __init__(self, strategy: LoadBalancingStrategy = LoadBalancingStrategy.ROUND_ROBIN):
        self.strategy = strategy
        self._endpoints: Dict[str, List[ModelEndpoint]] = {}  # model_name -> endpoints
        self._round_robin_counters: Dict[str, int] = {}

    def register_endpoints(self, model_name: str, endpoints: List[ModelEndpoint]):
        """Register endpoints for a model."""
        self._endpoints[model_name] = [e for e in endpoints if e.provider_instance.is_healthy()]
        self._round_robin_counters[model_name] = 0

    def get_endpoint(self, model_name: str) -> Optional[ModelEndpoint]:
        """Select an endpoint based on strategy."""
        endpoints = self._endpoints.get(model_name, [])
        healthy_endpoints = [e for e in endpoints if e.provider_instance.is_healthy()]

        if not healthy_endpoints:
            return None

        if self.strategy == LoadBalancingStrategy.ROUND_ROBIN:
            return self._round_robin_select(model_name, healthy_endpoints)
        elif self.strategy == LoadBalancingStrategy.LEAST_LATENCY:
            return self._least_latency_select(healthy_endpoints)
        elif self.strategy == LoadBalancingStrategy.COST_AWARE:
            return self._cost_aware_select(healthy_endpoints)
        elif self.strategy == LoadBalancingStrategy.RANDOM:
            return random.choice(healthy_endpoints)

        return healthy_endpoints[0]

    def _round_robin_select(self, model_name: str, endpoints: List[ModelEndpoint]) -> ModelEndpoint:
        counter = self._round_robin_counters.get(model_name, 0)
        endpoint = endpoints[counter % len(endpoints)]
        self._round_robin_counters[model_name] = counter + 1
        return endpoint

    def _least_latency_select(self, endpoints: List[ModelEndpoint]) -> ModelEndpoint:
        # Sort by estimated latency (would need historical data)
        # For now, use provider priority as proxy
        return min(endpoints, key=lambda e: -e.provider.priority)

    def _cost_aware_select(self, endpoints: List[ModelEndpoint]) -> ModelEndpoint:
        # Sort by cost per token (input + output)
        return min(endpoints, key=lambda e: e.model.input_cost_per_1k + e.model.output_cost_per_1k)


class LLMService:
    """Main LLM service orchestrating providers, load balancing, and cost tracking."""

    def __init__(self):
        self.load_balancer = LoadBalancer(LoadBalancingStrategy(settings.LB_STRATEGY))
        self._initialized = False

    async def initialize(self, tenant_id: str):
        """Load provider/model configs from DB and initialize endpoints."""
        from uuid import UUID
        tenant_uuid = UUID(tenant_id)

        async with session_context() as session:
            # Load active providers
            stmt = select(ProviderConfig).where(
                ProviderConfig.tenant_id == tenant_uuid,
                ProviderConfig.status == ProviderStatus.ACTIVE,
            )
            result = await session.execute(stmt)
            providers = result.scalars().all()

            # Load active models
            stmt = select(ModelConfig).where(
                ModelConfig.tenant_id == tenant_uuid,
                ModelConfig.is_active == True,
            )
            result = await session.execute(stmt)
            models = result.scalars().all()

            # Group models by name
            models_by_name: Dict[str, List[ModelConfig]] = {}
            for model in models:
                models_by_name.setdefault(model.name, []).append(model)

            # Create endpoints for each model
            for model_name, model_list in models_by_name.items():
                endpoints = []
                for model in model_list:
                    provider = next((p for p in providers if p.id == model.provider_id), None)
                    if provider and provider.status == ProviderStatus.ACTIVE:
                        try:
                            provider_instance = ProviderFactory.create(provider, model)
                            endpoints.append(ModelEndpoint(
                                provider=provider,
                                model=model,
                                provider_instance=provider_instance,
                                weight=float(provider.priority or 1),
                            ))
                        except Exception as e:
                            logger.warning("Failed to create provider instance", provider=provider.name, model=model.name, error=str(e))

                if endpoints:
                    self.load_balancer.register_endpoints(model_name, endpoints)

            self._initialized = True
            logger.info("LLM service initialized", tenant_id=tenant_id, models=list(models_by_name.keys()))

    async def _ensure_initialized(self, tenant_id: str):
        if not self._initialized:
            await self.initialize(tenant_id)

    async def chat_completion(
        self,
        tenant_id: str,
        user_id: Optional[str],
        request: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Non-streaming chat completion with fallback."""
        from uuid import UUID
        await self._ensure_initialized(tenant_id)

        model_name = request["model"]
        endpoint = self.load_balancer.get_endpoint(model_name)

        if not endpoint:
            raise ValueError(f"No healthy provider for model: {model_name}")

        request_id = f"req-{uuid.uuid4().hex[:12]}"
        start_time = time.perf_counter()

        try:
            result = await endpoint.provider_instance.chat_completion(request)
            latency_ms = result["latency_ms"]
            usage = result["usage"]

            # Record usage
            await self._record_usage(
                tenant_id=UUID(tenant_id),
                user_id=UUID(user_id) if user_id else None,
                provider_id=endpoint.provider.id,
                model_id=endpoint.model.id,
                request_id=request_id,
                model_type=endpoint.model.model_type,
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
                total_tokens=usage["total_tokens"],
                latency_ms=latency_ms,
                status="success",
            )

            return result["response"]

        except Exception as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            await self._record_usage(
                tenant_id=UUID(tenant_id),
                user_id=UUID(user_id) if user_id else None,
                provider_id=endpoint.provider.id,
                model_id=endpoint.model.id,
                request_id=request_id,
                model_type=endpoint.model.model_type,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                latency_ms=latency_ms,
                status="error",
                error_message=str(e),
            )
            raise

    async def stream_chat_completion(
        self,
        tenant_id: str,
        user_id: Optional[str],
        request: Dict[str, Any],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Streaming chat completion."""
        from uuid import UUID
        await self._ensure_initialized(tenant_id)

        model_name = request["model"]
        endpoint = self.load_balancer.get_endpoint(model_name)

        if not endpoint:
            raise ValueError(f"No healthy provider for model: {model_name}")

        request_id = f"req-{uuid.uuid4().hex[:12]}"
        start_time = time.perf_counter()
        total_prompt_tokens = 0
        total_completion_tokens = 0
        chunk_count = 0

        try:
            async for chunk in endpoint.provider_instance.stream_chat_completion(request):
                chunk_count += 1
                # Estimate tokens from first chunk (rough)
                if chunk_count == 1:
                    import tiktoken
                    encoding = tiktoken.get_encoding("cl100k_base")
                    total_prompt_tokens = sum(len(encoding.encode(m["content"])) for m in request["messages"])
                yield chunk
        except Exception as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            await self._record_usage(
                tenant_id=UUID(tenant_id),
                user_id=UUID(user_id) if user_id else None,
                provider_id=endpoint.provider.id,
                model_id=endpoint.model.id,
                request_id=request_id,
                model_type=endpoint.model.model_type,
                prompt_tokens=total_prompt_tokens,
                completion_tokens=total_completion_tokens,
                total_tokens=total_prompt_tokens + total_completion_tokens,
                latency_ms=latency_ms,
                status="error",
                error_message=str(e),
            )
            raise
        finally:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            if chunk_count > 0:
                await self._record_usage(
                    tenant_id=UUID(tenant_id),
                    user_id=UUID(user_id) if user_id else None,
                    provider_id=endpoint.provider.id,
                    model_id=endpoint.model.id,
                    request_id=request_id,
                    model_type=endpoint.model.model_type,
                    prompt_tokens=total_prompt_tokens,
                    completion_tokens=total_completion_tokens,
                    total_tokens=total_prompt_tokens + total_completion_tokens,
                    latency_ms=latency_ms,
                    status="success",
                )

    async def embeddings(
        self,
        tenant_id: str,
        user_id: Optional[str],
        request: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Generate embeddings."""
        from uuid import UUID
        await self._ensure_initialized(tenant_id)

        model_name = request["model"]
        endpoint = self.load_balancer.get_endpoint(model_name)

        if not endpoint:
            raise ValueError(f"No healthy provider for model: {model_name}")

        request_id = f"req-{uuid.uuid4().hex[:12]}"
        start_time = time.perf_counter()

        try:
            result = await endpoint.provider_instance.embeddings(request)
            latency_ms = result["latency_ms"]
            usage = result["usage"]

            await self._record_usage(
                tenant_id=UUID(tenant_id),
                user_id=UUID(user_id) if user_id else None,
                provider_id=endpoint.provider.id,
                model_id=endpoint.model.id,
                request_id=request_id,
                model_type=ModelType.EMBEDDING,
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=0,
                total_tokens=usage["total_tokens"],
                latency_ms=latency_ms,
                status="success",
            )

            return result["response"]

        except Exception as e:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            await self._record_usage(
                tenant_id=UUID(tenant_id),
                user_id=UUID(user_id) if user_id else None,
                provider_id=endpoint.provider.id,
                model_id=endpoint.model.id,
                request_id=request_id,
                model_type=ModelType.EMBEDDING,
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                latency_ms=latency_ms,
                status="error",
                error_message=str(e),
            )
            raise

    async def _record_usage(
        self,
        tenant_id: UUID,
        user_id: Optional[UUID],
        provider_id: UUID,
        model_id: UUID,
        request_id: str,
        model_type: ModelType,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        latency_ms: int,
        status: str,
        error_message: Optional[str] = None,
    ):
        """Record usage for cost tracking."""
        if not settings.COST_TRACKING_ENABLED:
            return

        # Calculate estimated cost
        async with session_context() as session:
            model = await session.get(ModelConfig, model_id)
            if model:
                input_cost = (prompt_tokens / 1000) * model.input_cost_per_1k
                output_cost = (completion_tokens / 1000) * model.output_cost_per_1k
                estimated_cost = int(input_cost + output_cost)  # micro-USD
            else:
                estimated_cost = 0

            record = UsageRecord(
                tenant_id=tenant_id,
                user_id=user_id,
                provider_id=provider_id,
                model_id=model_id,
                request_id=request_id,
                model_type=model_type,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                estimated_cost_usd=estimated_cost,
                latency_ms=latency_ms,
                status=status,
                error_message=error_message,
            )
            session.add(record)

    async def get_models(self, tenant_id: str) -> List[Dict[str, Any]]:
        """List available models for tenant."""
        await self._ensure_initialized(tenant_id)

        models = []
        for model_name, endpoints in self.load_balancer._endpoints.items():
            if endpoints:
                endpoint = endpoints[0]
                models.append({
                    "id": model_name,
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": endpoint.provider.name,
                    "permission": [],
                    "root": model_name,
                    "parent": None,
                    "context_window": endpoint.model.context_window,
                    "max_output_tokens": endpoint.model.max_output_tokens,
                    "supports_streaming": endpoint.model.supports_streaming,
                    "supports_functions": endpoint.model.supports_functions,
                    "supports_vision": endpoint.model.supports_vision,
                })
        return models

    async def get_cost_summary(
        self,
        tenant_id: str,
        user_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get cost summary for tenant/user."""
        from uuid import UUID
        from datetime import datetime

        async with session_context() as session:
            stmt = select(UsageRecord).where(UsageRecord.tenant_id == UUID(tenant_id))

            if user_id:
                stmt = stmt.where(UsageRecord.user_id == UUID(user_id))
            if start_date:
                stmt = stmt.where(UsageRecord.created_at >= datetime.fromisoformat(start_date))
            if end_date:
                stmt = stmt.where(UsageRecord.created_at <= datetime.fromisoformat(end_date))

            result = await session.execute(stmt)
            records = result.scalars().all()

            total_tokens = sum(r.total_tokens for r in records)
            total_cost = sum(r.estimated_cost_usd for r in records) / 1_000_000  # Convert to USD

            by_model = {}
            by_provider = {}
            for r in records:
                by_model[str(r.model_id)] = by_model.get(str(r.model_id), 0) + r.estimated_cost_usd / 1_000_000
                by_provider[str(r.provider_id)] = by_provider.get(str(r.provider_id), 0) + r.estimated_cost_usd / 1_000_000

            return {
                "total_tokens": total_tokens,
                "total_cost_usd": round(total_cost, 6),
                "by_model": {k: round(v, 6) for k, v in by_model.items()},
                "by_provider": {k: round(v, 6) for k, v in by_provider.items()},
                "period_start": start_date,
                "period_end": end_date,
            }


llm_service = LLMService()