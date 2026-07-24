from functools import lru_cache

from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "RetailFlow Orders"
    app_env: str = "local"
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"

    database_url: str = "postgresql+asyncpg://retailflow:retailflow@localhost:5432/orders"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_order_events_topic: str = "retailflow.order-events.v1"
    outbox_batch_size: int = Field(default=100, ge=1, le=1000)
    outbox_lock_seconds: int = Field(default=30, ge=5, le=300)
    reconciliation_batch_size: int = Field(default=50, ge=1, le=500)

    inventory_base_url: AnyHttpUrl = AnyHttpUrl("http://localhost:8090")
    inventory_service_token: SecretStr = SecretStr("local-inventory-token")

    jwt_secret: SecretStr = Field(
        default=SecretStr("local-only-secret-change-before-deployment-0123456789"),
        min_length=32,
    )
    jwt_issuer: str = "retailflow-orders"
    jwt_audience: str = "retailflow-orders-api"
    access_token_ttl_seconds: int = Field(default=3600, ge=300, le=86400)
    idempotency_ttl_seconds: int = Field(default=86400, ge=3600, le=604800)
    idempotency_lock_seconds: int = Field(default=30, ge=5, le=300)
    product_cache_ttl_seconds: int = Field(default=300, ge=10, le=3600)

    admin_email: str = "admin@retailflow.local"
    admin_password: SecretStr = SecretStr("local-admin-password")


@lru_cache
def get_settings() -> Settings:
    return Settings()
