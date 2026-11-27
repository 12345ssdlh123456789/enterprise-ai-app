from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    APP_NAME: str = "workflow-service"
    APP_ENV: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8005

    # Database
    DB_AUTO_MIGRATE: bool = True  # 启动时用 Alembic 迁移建表；false 退回 create_all
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/enterprise_ai",
        description="PostgreSQL async connection string",
    )

    # Redis
    REDIS_URL: str = Field(
        default="redis://localhost:6379/5",
        description="Redis connection string",
    )

    # Celery
    CELERY_BROKER_URL: str = Field(
        default="redis://localhost:6379/5",
        description="Celery broker URL",
    )
    CELERY_RESULT_BACKEND: str = Field(
        default="redis://localhost:6379/5",
        description="Celery result backend",
    )

    # API Gateway (for internal calls)
    API_GATEWAY_URL: str = Field(
        default="http://localhost:8000",
        description="API Gateway base URL",
    )
    SERVICE_API_KEY: str = Field(default="", description="Service-to-service API key")

    # LLM Service
    LLM_SERVICE_URL: str = Field(
        default="http://localhost:8003",
        description="LLM Service URL",
    )

    # RAG Service
    RAG_SERVICE_URL: str = Field(
        default="http://localhost:8001",
        description="RAG Service URL",
    )

    # Execution
    MAX_CONCURRENT_EXECUTIONS: int = Field(default=10, description="Max concurrent workflow executions")
    EXECUTION_TIMEOUT_SECONDS: int = Field(default=300, description="Default execution timeout")
    RETRY_MAX_ATTEMPTS: int = Field(default=3, description="Max retry attempts for failed nodes")

    # Observability
    OTEL_EXPORTER_OTLP_ENDPOINT: str = Field(
        default="http://localhost:4317",
        description="OTLP exporter endpoint",
    )
    METRICS_PORT: int = Field(default=9095, description="Prometheus metrics port")


settings = Settings()