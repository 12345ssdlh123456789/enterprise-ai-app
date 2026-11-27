from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
import json


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    APP_NAME: str = "llm-service"
    APP_ENV: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8003

    # Database
    DB_AUTO_MIGRATE: bool = True  # 启动时用 Alembic 迁移建表；false 退回 create_all
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/enterprise_ai",
        description="PostgreSQL async connection string",
    )

    # Redis
    REDIS_URL: str = Field(
        default="redis://localhost:6379/3",
        description="Redis connection string",
    )

    # 服务间调用签名（网关/微服务互调必须带合法签名；留空 = 本地开发模式，不校验）
    SERVICE_API_KEY: str = ""

    # Provider API Keys
    OPENAI_API_KEY: str = Field(default="", description="OpenAI API key")
    OPENAI_API_BASE: str = Field(default="https://api.openai.com/v1", description="OpenAI API base URL")
    ANTHROPIC_API_KEY: str = Field(default="", description="Anthropic API key")
    ANTHROPIC_API_BASE: str = Field(default="https://api.anthropic.com", description="Anthropic API base URL")
    AZURE_OPENAI_API_KEY: str = Field(default="", description="Azure OpenAI API key")
    AZURE_OPENAI_ENDPOINT: str = Field(default="", description="Azure OpenAI endpoint")
    AZURE_OPENAI_API_VERSION: str = Field(default="2024-02-15-preview", description="Azure OpenAI API version")
    OLLAMA_BASE_URL: str = Field(default="http://localhost:11434", description="Ollama base URL")

    # Default Models
    DEFAULT_CHAT_MODEL: str = Field(default="gpt-4o-mini", description="Default chat model")
    DEFAULT_EMBEDDING_MODEL: str = Field(default="text-embedding-3-small", description="Default embedding model")

    # Load Balancing
    LB_STRATEGY: str = Field(default="round_robin", description="Load balancing strategy: round_robin, least_latency, cost_aware")
    MAX_RETRIES: int = Field(default=3, description="Max retries for provider calls")
    RETRY_BASE_DELAY: float = Field(default=1.0, description="Base delay for exponential backoff")
    TIMEOUT_SECONDS: float = Field(default=60.0, description="Request timeout")

    # Cost Tracking
    COST_TRACKING_ENABLED: bool = Field(default=True, description="Enable cost tracking")
    COST_PER_1K_TOKENS: str = Field(
        default='{"gpt-4o": {"input": 5.0, "output": 15.0}, "gpt-4o-mini": {"input": 0.15, "output": 0.6}, "claude-3-5-sonnet": {"input": 3.0, "output": 15.0}, "claude-3-haiku": {"input": 0.25, "output": 1.25}}',
        description="Cost per 1K tokens in USD (JSON string)",
    )

    # Circuit Breaker
    CB_FAILURE_THRESHOLD: int = Field(default=5, description="Circuit breaker failure threshold")
    CB_RECOVERY_TIMEOUT: int = Field(default=60, description="Circuit breaker recovery timeout (seconds)")
    CB_HALF_OPEN_REQUESTS: int = Field(default=3, description="Circuit breaker half-open requests")

    # Observability
    OTEL_EXPORTER_OTLP_ENDPOINT: str = Field(
        default="http://localhost:4317",
        description="OTLP exporter endpoint",
    )
    METRICS_PORT: int = Field(default=9093, description="Prometheus metrics port")

    @property
    def cost_per_1k_tokens(self) -> dict:
        try:
            return json.loads(self.COST_PER_1K_TOKENS)
        except Exception:
            return {}


settings = Settings()