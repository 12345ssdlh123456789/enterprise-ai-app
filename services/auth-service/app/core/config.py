"""Auth Service core configuration."""

from typing import List

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Server
    port: int = 8000
    host: str = "0.0.0.0"

    # Database
    db_auto_migrate: bool = True  # 启动时用 Alembic 迁移建表；false 退回 create_all
    database_url: str = "sqlite+aiosqlite:///./auth.db"
    database_pool_size: int = 10
    database_max_overflow: int = 20

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # JWT
    jwt_secret_key: str = "change-this-secret-key-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7

    # 服务间调用签名（网关/微服务互调必须带合法签名；留空 = 本地开发模式，不校验）
    SERVICE_API_KEY: str = ""

    # Logging
    log_level: str = "INFO"

    # CORS
    cors_origins: str = "http://localhost:3000,http://localhost:8000,http://127.0.0.1:3002,http://localhost:3002"

    # OpenTelemetry
    otel_exporter_otlp_endpoint: str = "http://jaeger:4317"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
