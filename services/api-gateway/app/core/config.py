# API Gateway - Configuration

from typing import Annotated, List, Optional
import secrets

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # App
    APP_NAME: str = "智汇 AI 工作台 - API 网关"
    APP_VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    API_PREFIX: str = "/api/v1"
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Database
    # 默认 SQLite：开箱即用，不需要 Docker/Postgres。
    # 生产或 docker-compose 环境把 DATABASE_URL 换成
    #   postgresql+asyncpg://user:pass@host:5432/db
    # 即可自动切回 PostgreSQL（模型层已做类型兼容）。
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///./data/enterprise_ai.db",
        validation_alias="DATABASE_URL",
    )
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10
    DATABASE_POOL_TIMEOUT: int = 30
    DATABASE_ECHO: bool = False
    # 启动时用 Alembic 迁移建表（生产默认）。
    # 设为 false 则退回 Base.metadata.create_all，仅用于「不想引入迁移」的临时环境。
    DB_AUTO_MIGRATE: bool = Field(default=True, validation_alias="DB_AUTO_MIGRATE")

    # Redis (可选：没装 Redis 时设 REDIS_ENABLED=false)
    REDIS_ENABLED: bool = True
    REDIS_URL: str = Field(default="redis://127.0.0.1:6379/0", validation_alias="REDIS_URL")
    REDIS_MAX_RETRIES: int = 3
    REDIS_RETRY_DELAY: int = 100
    REDIS_CONNECT_TIMEOUT: int = 10000

    # Auth
    JWT_SECRET: str = Field(
        default_factory=lambda: secrets.token_urlsafe(64),
        validation_alias="JWT_SECRET",
    )
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    BCRYPT_ROUNDS: int = 12

    # CORS：.env 里用逗号分隔即可（NoDecode 关闭 JSON 解析）
    CORS_ORIGINS: Annotated[List[str], NoDecode] = Field(
        default=[
            "http://localhost:3000",
            "http://localhost:3001",
            "http://localhost:3002",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:3001",
            "http://127.0.0.1:3002",
        ],
        validation_alias="CORS_ORIGINS",
    )

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    # Rate Limiting
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    RATE_LIMIT_MAX_REQUESTS: int = 100
    RATE_LIMIT_MAX_TOKENS: int = 100000

    # LLM
    # ollama: 本地模型，零成本；openai / nvidia: OpenAI 兼容接口
    LLM_PROVIDER: str = "ollama"
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434"
    OLLAMA_CHAT_MODEL: str = "qwen2.5-coder:1.5b"
    OLLAMA_EMBEDDING_MODEL: str = "embeddinggemma:300m"
    OLLAMA_EMBEDDING_DIM: int = 768

    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    DEFAULT_CHAT_MODEL: str = "gpt-4o-mini"
    DEFAULT_EMBEDDING_MODEL: str = "text-embedding-3-small"

    NVIDIA_API_KEY: str = ""
    NVIDIA_BASE_URL: str = "https://integrate.api.nvidia.com/v1"

    EMBEDDING_PROVIDER: str = "ollama"
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIM: int = 768

    # RAG
    DEFAULT_CHUNK_SIZE: int = 800
    DEFAULT_CHUNK_OVERLAP: int = 120
    DEFAULT_TOP_K: int = 5
    RAG_MAX_CONTEXT_CHUNKS: int = 6

    # Internal services (地址按 AGENTS.md 的端口表；rag 是 8001、auth 是 8007)
    LLM_SERVICE_URL: str = "http://127.0.0.1:8003"
    RAG_SERVICE_URL: str = "http://127.0.0.1:8001"
    AUTH_SERVICE_URL: str = "http://127.0.0.1:8007"
    DOCUMENT_SERVICE_URL: str = "http://127.0.0.1:8004"
    WORKFLOW_SERVICE_URL: str = "http://127.0.0.1:8005"
    NOTIFICATION_SERVICE_URL: str = "http://127.0.0.1:8006"
    # 网关 → document-service 转发开关（试点）。默认关：单体形态仍由网关自己处理文档接口。
    # 打开前请显式配置 SERVICE_API_KEY（与微服务一致），否则转发会返回 503。
    GATEWAY_PROXY_DOCUMENTS: bool = False
    # 同理：/workflows 转发给 workflow-service（同样需要 SERVICE_API_KEY）
    GATEWAY_PROXY_WORKFLOWS: bool = False
    # 同理：/notifications 转发给 notification-service（第 26 轮对齐契约后开放）
    GATEWAY_PROXY_NOTIFICATIONS: bool = False
    SERVICE_API_KEY: str = Field(
        default_factory=lambda: secrets.token_urlsafe(32),
        validation_alias="SERVICE_API_KEY",
    )

    # Monitoring
    ENABLE_METRICS: bool = True
    METRICS_PORT: int = 9090
    ENABLE_TRACING: bool = False
    OTEL_EXPORTER_OTLP_ENDPOINT: Optional[str] = None
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "pretty"

    # File Upload
    MAX_FILE_SIZE_MB: int = 50
    ALLOWED_FILE_TYPES: str = "pdf,docx,txt,md,html,csv,json,pptx,xlsx"
    UPLOAD_DIR: str = "./data/uploads"
    TEMP_DIR: str = "./data/tmp"

    # Features
    ENABLE_RAG: bool = True
    ENABLE_WORKFLOWS: bool = True
    ENABLE_MULTIMODAL: bool = False
    ENABLE_ANALYTICS: bool = True
    ENABLE_AUDIT_LOG: bool = True

    # Bootstrap（首次启动自动创建演示租户/管理员）
    BOOTSTRAP_DEMO_DATA: bool = True
    BOOTSTRAP_ADMIN_EMAIL: str = "admin@example.com"
    BOOTSTRAP_ADMIN_PASSWORD: str = "admin123"

    @computed_field  # type: ignore[misc]
    @property
    def IS_SQLITE(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

    @computed_field  # type: ignore[misc]
    @property
    def ASYNC_DATABASE_URL(self) -> str:
        """把 DATABASE_URL 归一化成 async 驱动可用的形式。"""
        url = self.DATABASE_URL
        if url.startswith("postgresql+asyncpg://"):
            return url
        if url.startswith("postgresql://") or url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql://", 1).replace(
                "postgresql://", "postgresql+asyncpg://", 1
            )
        if url.startswith("sqlite+aiosqlite://"):
            return url
        if url.startswith("sqlite:///"):
            return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
        return url

    @computed_field  # type: ignore[misc]
    @property
    def SYNC_DATABASE_URL(self) -> str:
        """同步引擎（Alembic / Celery）用的 URL。"""
        return (
            self.ASYNC_DATABASE_URL.replace("+asyncpg", "").replace("+aiosqlite", "")
        )


settings = Settings()
