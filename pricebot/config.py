from functools import lru_cache
from typing import Any, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from pricebot.platform_env import (
    compose_database_url,
    compose_public_urls,
    compose_redis_url,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    bot_token: str
    webapp_url: str
    admin_ids: list[int] = Field(default_factory=list)
    database_url: str
    redis_url: str
    timezone: str = "Europe/Moscow"
    page_size: int = 10
    page_size_web: int = 20
    max_import_rows: int = 50_000
    payment_provider: str = "fake"
    payment_webhook_secret: str = "change-me-payment-webhook"
    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""
    yookassa_return_url: str = ""
    yookassa_trusted_ips: str = ""
    telegram_webhook_secret: str = "change-me-telegram-webhook"
    allow_paid_broadcast: bool = False
    bot_mode: str = "polling"
    public_base_url: str = "http://localhost:8080"
    host: str = "0.0.0.0"
    port: int = 8080
    media_dir: str = "data/media"
    imports_dir: str = "data/imports"
    backups_dir: str = "data/backups"
    backup_retention_days: int = 7
    domain: str = ""
    postgres_user: str = ""
    postgres_password: str = ""
    postgres_host: str = ""
    postgres_port: int = 5432
    postgres_db: str = ""
    redis_host: str = ""
    redis_port: int = 6379
    redis_password: str = ""

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, value: Any) -> list[int]:
        if value is None or value == "":
            return []
        if isinstance(value, list):
            return [int(item) for item in value]
        text = str(value).strip()
        if not text:
            return []
        return [int(part.strip()) for part in text.split(",") if part.strip()]

    @model_validator(mode="after")
    def _apply_platform_env(self) -> Self:
        self.public_base_url, self.webapp_url = compose_public_urls(
            domain=self.domain,
            public_base_url=self.public_base_url,
            webapp_url=self.webapp_url,
        )
        self.database_url = compose_database_url(
            self.database_url,
            host=self.postgres_host,
            user=self.postgres_user,
            password=self.postgres_password,
            port=self.postgres_port,
            database=self.postgres_db,
        )
        self.redis_url = compose_redis_url(
            self.redis_url,
            host=self.redis_host,
            password=self.redis_password,
            port=self.redis_port,
        )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
