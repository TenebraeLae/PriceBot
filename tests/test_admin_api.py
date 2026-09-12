from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from pricebot.db.models import Product
from pricebot.db.session import create_schema, make_engine, make_session_factory
from pricebot.web.deps import get_session, get_settings_dep
from sqlalchemy import text

from pricebot.web.main import app
from tests.conftest import init_data_headers, make_test_settings, write_xlsx

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _client(tmp_path: Path):
    settings = make_test_settings(tmp_path)
    engine = make_engine(settings.database_url)

    async def _prepare() -> None:
        await create_schema(engine)

    import asyncio

    asyncio.run(_prepare())
    factory = make_session_factory(engine)

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_settings_dep] = lambda: settings
    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    return client, settings, factory, engine


def _cleanup(engine) -> None:
    app.dependency_overrides.clear()
    import asyncio

    asyncio.run(engine.dispose())


def test_admin_import_and_search_roundtrip(tmp_path: Path) -> None:
    client, settings, factory, engine = _client(tmp_path)
    try:
        path = tmp_path / "ok.xlsx"
        write_xlsx(
            path,
            ["sku", "name", "price", "stock", "category", "description"],
            [["CEM-M500", "Цемент М500", "450.00", 12, "Сухие смеси", "Мешок 50 кг"]],
        )
        denied = client.post(
            "/api/v1/admin/import",
            files={"file": ("ok.xlsx", path.read_bytes(), XLSX_MIME)},
            headers={"X-Telegram-Id": "9"},
        )
        assert denied.status_code == 403

        uploaded = client.post(
            "/api/v1/admin/import",
            files={"file": ("ok.xlsx", path.read_bytes(), XLSX_MIME)},
            headers={"X-Telegram-Id": "1001"},
        )
        assert uploaded.status_code == 200
        body = uploaded.json()
        assert body["status"] == "applied"
        assert body["rows_ok"] == 1

        web = init_data_headers(settings)
        empty = client.get("/api/v1/search", params={"q": "   "}, headers=web)
        assert empty.status_code == 200
        assert empty.json()["items"] == []
        assert empty.json()["reason"] == "empty_query"

        found = client.get("/api/v1/search", params={"q": "цемент М500"}, headers=web)
        assert found.status_code == 200
        items = found.json()["items"]
        assert items[0]["sku"] == "CEM-M500"
        assert items[0]["price"] == "450.00"

        card = client.get("/api/v1/products/CEM-M500", headers=web)
        assert card.status_code == 200
        assert card.json()["photo_url"] is None
        assert card.json()["availability"] == "в наличии"

        injection = client.get("/api/v1/search", params={"q": "%' OR 1=1"}, headers=web)
        assert injection.json()["items"] == []

        past = client.get("/api/v1/search", params={"q": "цемент", "page": 0}, headers=web)
        assert past.json()["items"] == []
    finally:
        _cleanup(engine)


def test_admin_reject_keeps_catalog(tmp_path: Path) -> None:
    client, settings, factory, engine = _client(tmp_path)
    try:
        good = tmp_path / "good.xlsx"
        write_xlsx(good, ["sku", "name", "price"], [["KEEP-1", "Оставить", 9]])
        client.post(
            "/api/v1/admin/import",
            files={"file": ("good.xlsx", good.read_bytes(), XLSX_MIME)},
            headers={"X-Telegram-Id": "1001"},
        )
        bad = tmp_path / "bad.xlsx"
        write_xlsx(bad, ["foo", "bar"], [["a", "b"]])
        rejected = client.post(
            "/api/v1/admin/import",
            files={"file": ("bad.xlsx", bad.read_bytes(), XLSX_MIME)},
            headers={"X-Telegram-Id": "1001"},
        )
        assert rejected.json()["status"] == "rejected"

        async def _count() -> int:
            async with factory() as session:
                return int(
                    await session.scalar(
                        select(func.count()).select_from(Product).where(Product.sku == "KEEP-1")
                    )
                    or 0
                )

        import asyncio

        assert asyncio.run(_count()) == 1
        assert list(Path(settings.imports_dir).glob("*.xlsx"))
    finally:
        _cleanup(engine)


@pytest.mark.asyncio
async def test_web_lifespan_creates_schema(tmp_path: Path, monkeypatch) -> None:
    settings = make_test_settings(tmp_path)
    monkeypatch.setattr("pricebot.web.main.get_settings", lambda: settings)
    async with app.router.lifespan_context(app):
        async with app.state.engine.connect() as connection:
            name = await connection.scalar(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='products'")
            )
        assert name == "products"
