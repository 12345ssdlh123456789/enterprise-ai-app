from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    APP_NAME: str = "document-service"
    APP_ENV: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8004

    # Database
    DB_AUTO_MIGRATE: bool = True  # 启动时用 Alembic 迁移建表；false 退回 create_all
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/enterprise_ai",
        description="PostgreSQL async connection string",
    )

    # Redis
    REDIS_URL: str = Field(
        default="redis://localhost:6379/4",
        description="Redis connection string",
    )

    # 对象存储：minio（S3 兼容）或 local（本地目录，零依赖开发用）
    STORAGE_PROVIDER: str = Field(default="minio", description="minio | local")
    STORAGE_LOCAL_DIR: str = Field(default="./data/storage", description="local provider 的根目录")
    PUBLIC_BASE_URL: str = Field(
        default="http://127.0.0.1:8004",
        description="local provider 签发 presigned URL 时用的对外地址",
    )

    # MinIO
    MINIO_ENDPOINT: str = Field(default="localhost:9000", description="MinIO endpoint")
    MINIO_ACCESS_KEY: str = Field(default="minioadmin", description="MinIO access key")
    MINIO_SECRET_KEY: str = Field(default="minioadmin123", description="MinIO secret key")
    MINIO_BUCKET: str = Field(default="documents", description="MinIO bucket name")
    MINIO_USE_SSL: bool = Field(default=False, description="Use SSL for MinIO")
    MINIO_REGION: str = Field(default="us-east-1", description="MinIO region")

    # File Processing
    MAX_FILE_SIZE: int = Field(default=100 * 1024 * 1024, description="Max file size in bytes (100MB)")
    ALLOWED_MIME_TYPES: str = Field(
        default="application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown,image/png,image/jpeg,image/tiff",
        description="Comma-separated allowed MIME types",
    )
    UPLOAD_DIR: str = Field(default="/app/uploads", description="Local upload directory")

    # OCR
    TESSERACT_CMD: str = Field(default="tesseract", description="Tesseract command path")
    TESSERACT_LANG: str = Field(default="chi_sim+eng", description="Tesseract languages")

    # API Gateway (for callbacks)
    API_GATEWAY_URL: str = Field(default="http://localhost:8000", description="API Gateway base URL")
    SERVICE_API_KEY: str = Field(default="", description="Service-to-service API key")

    # 预签名 /upload/complete 成功后是否自动解析（解析成功才会继续自动入库）
    AUTO_PROCESS_ON_UPLOAD: bool = Field(
        default=True, description="complete 后自动解析文档（预签名上传链路）"
    )

    # RAG 自动入库：解析成功后把正文直接送 rag-service 分块/嵌入（零手工步骤）
    RAG_SERVICE_URL: str = Field(default="http://127.0.0.1:8001", description="rag-service base URL")
    AUTO_INGEST_TO_RAG: bool = Field(default=True, description="解析成功后自动 ingest 到 rag-service")

    # Observability
    OTEL_EXPORTER_OTLP_ENDPOINT: str = Field(
        default="http://localhost:4317",
        description="OTLP exporter endpoint",
    )
    METRICS_PORT: int = Field(default=9094, description="Prometheus metrics port")

    @property
    def allowed_mime_types_list(self) -> list[str]:
        return [t.strip() for t in self.ALLOWED_MIME_TYPES.split(",")]


settings = Settings()