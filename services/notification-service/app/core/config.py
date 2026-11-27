"""Notification Service core configuration."""

from typing import List

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    port: int = 8006
    host: str = "0.0.0.0"

    db_auto_migrate: bool = True  # 启动时用 Alembic 迁移建表；false 退回 create_all
    database_url: str = "sqlite+aiosqlite:///./notification.db"
    database_pool_size: int = 10
    database_max_overflow: int = 20

    redis_url: str = "redis://redis:6379/1"

    smtp_host: str = "smtp.example.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""

    # 服务间调用签名（网关/微服务互调必须带合法签名；留空 = 本地开发模式，不校验）
    SERVICE_API_KEY: str = ""
    smtp_from: str = "noreply@example.com"

    webhook_timeout_seconds: int = 10

    log_level: str = "INFO"

    cors_origins: str = "http://localhost:3000,http://localhost:8000"

    otel_exporter_otlp_endpoint: str = "http://jaeger:4317"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
