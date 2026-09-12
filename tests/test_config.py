from pricebot.config import Settings
from pricebot.platform_env import (
    database_host,
    is_compose_only_db_url,
    normalize_database_url,
    unreachable_database_message,
)
from pricebot.db.models import (
    Cart,
    Category,
    Order,
    Payment,
    PriceImport,
    Product,
    PromoCode,
    SupportTicket,
    User,
)
from pricebot.web.main import app


def test_admin_ids_comma_separated() -> None:
    settings = Settings(
        bot_token="1:token",
        webapp_url="https://example.invalid/app",
        admin_ids="111,222",
        database_url="postgresql+asyncpg://u:p@localhost/db",
        redis_url="redis://localhost:6379/0",
    )
    assert settings.admin_ids == [111, 222]
    assert settings.timezone == "Europe/Moscow"
    assert settings.page_size == 10
    assert settings.page_size_web == 20
    assert settings.allow_paid_broadcast is False
    assert settings.payment_webhook_secret != settings.telegram_webhook_secret


def test_platform_env_rewrites_loopback_urls() -> None:
    settings = Settings(
        bot_token="1:token",
        webapp_url="http://localhost:8080/app/",
        admin_ids="111",
        database_url="postgresql+asyncpg://u:p@localhost:5432/db",
        redis_url="redis://localhost:6379/0",
        domain="shop.bothost.tech",
        postgres_host="pg.internal",
        postgres_user="u",
        postgres_password="p",
        postgres_db="db",
        redis_host="redis.internal",
        _env_file=None,
    )
    assert settings.public_base_url == "https://shop.bothost.tech"
    assert settings.webapp_url == "https://shop.bothost.tech/app/"
    assert settings.bot_mode == "webhook"
    assert settings.database_url == "postgresql+asyncpg://u:p@pg.internal:5432/db"
    assert settings.redis_url == "redis://redis.internal:6379/0"


def test_normalize_bothost_postgresql_url() -> None:
    raw = "postgresql://u:p@node1.pghost.ru:16100/db"
    assert normalize_database_url(raw) == "postgresql+asyncpg://u:p@node1.pghost.ru:16100/db"
    settings = Settings(
        bot_token="1:token",
        webapp_url="https://example.invalid/app",
        database_url=raw,
        redis_url="redis://localhost:6379/0",
        _env_file=None,
    )
    assert settings.database_url.startswith("postgresql+asyncpg://")


def test_compose_postgres_host_is_not_for_bothost() -> None:
    url = "postgresql+asyncpg://u:p@postgres:5432/pricebot"
    assert database_host(url) == "postgres"
    assert is_compose_only_db_url(url)
    assert "postgres" in unreachable_database_message(url)


def test_models_have_required_fields() -> None:
    assert User.__tablename__ == "users"
    assert Product.sku.property.columns[0].unique
    assert Order.number.property.columns[0].unique
    assert Cart.user_id.property.columns[0].unique
    assert Payment.__table_args__
    assert Category.__tablename__ == "categories"
    assert PriceImport.__tablename__ == "imports"
    assert PromoCode.__tablename__ == "promo_codes"
    assert SupportTicket.__tablename__ == "support_tickets"


def test_fastapi_slot_stub() -> None:
    from fastapi.testclient import TestClient

    client = TestClient(app)
    payload = client.get("/api/v1/slot").json()
    assert payload["slot"] == "miniapp"
    assert payload["stage"] == "E"
    assert payload["ready"] is True
    assert client.get("/api/slot").json() == payload
    assert client.get("/health").json() == {"ok": True}
    assert client.get("/").json() == {"ok": True}
