import hashlib
import hmac
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import pytest
from openpyxl import Workbook

from pricebot.config import Settings
from pricebot.db.session import create_schema, make_engine, make_session_factory
from pricebot.domain.catalog import CatalogProduct

MOSCOW = ZoneInfo("Europe/Moscow")


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 9, 12, 12, 0, tzinfo=MOSCOW)


@pytest.fixture
def cement() -> CatalogProduct:
    return CatalogProduct(
        sku="CEM-M500",
        name="Цемент М500",
        category="Сухие смеси",
        description="Мешок 50 кг",
        price=Decimal("450.00"),
        stock=Decimal(12),
        unit="мешок",
        sort=10,
    )


@pytest.fixture
def sand() -> CatalogProduct:
    return CatalogProduct(
        sku="SAND-01",
        name="Песок речной",
        category="Сыпучие",
        price=Decimal("80.00"),
        stock=Decimal(2),
        unit="кг",
        sort=20,
    )


@pytest.fixture
def hidden() -> CatalogProduct:
    return CatalogProduct(
        sku="HIDE-1",
        name="Скрытый цемент",
        category="Сухие смеси",
        price=Decimal("1.00"),
        stock=Decimal(5),
        active=False,
        sort=1,
    )


@pytest.fixture
def catalog(
    cement: CatalogProduct, sand: CatalogProduct, hidden: CatalogProduct
) -> list[CatalogProduct]:
    return [cement, sand, hidden]


def write_xlsx(path: Path, headers: list[str], rows: list[list[object]]) -> Path:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    return path


def make_test_settings(tmp_path: Path, *, admin_id: int = 1001) -> Settings:
    return Settings(
        bot_token="1:test-token",
        webapp_url="https://example.invalid/app",
        admin_ids=[admin_id],
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'pricebot.db'}",
        redis_url="redis://localhost:6379/15",
        imports_dir=str(tmp_path / "imports"),
        media_dir=str(tmp_path / "media"),
        backups_dir=str(tmp_path / "backups"),
        page_size=10,
        page_size_web=20,
    )


def make_init_data(bot_token: str, telegram_id: int, username: str = "buyer") -> str:
    user = json.dumps({"id": telegram_id, "username": username}, separators=(",", ":"))
    fields = {"auth_date": "1770000000", "query_id": "AAEtest", "user": user}
    check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    digest = hmac.new(secret, check.encode("utf-8"), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": digest})


def init_data_headers(settings: Settings, telegram_id: int = 555) -> dict[str, str]:
    return {"X-Telegram-Init-Data": make_init_data(settings.bot_token, telegram_id)}


@pytest.fixture
async def db_engine(tmp_path: Path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'pricebot.db'}")
    await create_schema(engine)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(db_engine):
    return make_session_factory(db_engine)


@pytest.fixture
async def db_session(session_factory):
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    return make_test_settings(tmp_path)
