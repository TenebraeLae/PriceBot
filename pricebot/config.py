from functools import lru_cache
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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


@lru_cache
def get_settings() -> Settings:
    return Settings()
