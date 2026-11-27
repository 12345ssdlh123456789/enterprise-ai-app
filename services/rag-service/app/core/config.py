from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    APP_NAME: str = "rag-service"
    APP_ENV: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8001

    # Database (PostgreSQL + pgvector)
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/enterprise_ai",
        description="PostgreSQL async connection string",
    )
    # 启动时用 Alembic 迁移建表（生产默认）。
    # 设为 false 则退回 Base.metadata.create_all，仅用于临时环境。
    DB_AUTO_MIGRATE: bool = Field(default=True, validation_alias="DB_AUTO_MIGRATE")

    # Redis
    REDIS_URL: str = Field(
        default="redis://localhost:6379/1",
        description="Redis connection string",
    )

    # Embedding Model (配置化，支持任意 OpenAI 兼容 API)
    EMBEDDING_API_KEY: str = Field(default="", description="Embedding model API key")
    EMBEDDING_API_BASE: str = Field(
        default="https://api.openai.com/v1",
        description="Embedding model API base URL",
    )
    EMBEDDING_MODEL: str = Field(
        default="text-embedding-3-small",
        description="Embedding model name",
    )
    EMBEDDING_DIM: int = Field(
        default=1536,
        description="Embedding vector dimension",
    )
    EMBEDDING_BATCH_SIZE: int = Field(default=100, description="Batch size for embedding requests")

    # Cohere Rerank
    COHERE_API_KEY: str = Field(default="", description="Cohere API key for rerank")
    RERANK_MODEL: str = Field(default="rerank-v3.5", description="Cohere rerank model")
    RERANK_TOP_K: int = Field(default=10, description="Number of docs to rerank")

    # Chunking
    CHUNK_SIZE: int = Field(default=1000, description="Chunk size in tokens/chars")
    CHUNK_OVERLAP: int = Field(default=200, description="Chunk overlap in tokens/chars")
    CHUNK_MIN_SIZE: int = Field(default=100, description="Minimum chunk size")

    # Retrieval
    RETRIEVAL_TOP_K: int = Field(default=20, description="Initial retrieval top-k")
    RETRIEVAL_FINAL_K: int = Field(default=5, description="Final top-k after rerank")
    RRF_K: int = Field(default=60, description="RRF fusion parameter")

    # BM25
    BM25_INDEX_PATH: str = Field(default="/data/bm25_index", description="BM25 index storage path")

    # API Gateway (for internal calls)
    API_GATEWAY_URL: str = Field(
        default="http://localhost:8000",
        description="API Gateway base URL",
    )
    SERVICE_API_KEY: str = Field(default="", description="Service-to-service API key")

    # Observability
    OTEL_EXPORTER_OTLP_ENDPOINT: str = Field(
        default="http://localhost:4317",
        description="OTLP exporter endpoint",
    )
    METRICS_PORT: int = Field(default=9091, description="Prometheus metrics port")


settings = Settings()