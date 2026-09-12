from pricebot.config import Settings
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
