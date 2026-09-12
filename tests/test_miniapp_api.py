import asyncio
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import update

from pricebot.db.models import User
from pricebot.db.session import create_schema, make_engine, make_session_factory
from pricebot.web.deps import get_session, get_settings_dep
from pricebot.web.main import APP_DIR, app
from tests.conftest import admin_headers, init_data_headers, make_init_data, make_test_settings, write_xlsx

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _client(tmp_path: Path):
    settings = make_test_settings(tmp_path)
    engine = make_engine(settings.database_url)
    asyncio.run(create_schema(engine))
    factory = make_session_factory(engine)

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_settings_dep] = lambda: settings
    app.dependency_overrides[get_session] = override_session
    return TestClient(app), settings, factory, engine


def _cleanup(engine) -> None:
    app.dependency_overrides.clear()
    asyncio.run(engine.dispose())


def _import_catalog(
    client,
    tmp_path: Path,
    rows: list[list[object]],
    headers: list[str] | None = None,
) -> None:
    path = tmp_path / "cat.xlsx"
    write_xlsx(
        path,
        headers
        or ["sku", "name", "price", "stock", "category", "description", "sort"],
        rows,
    )
    settings = client.app.dependency_overrides[get_settings_dep]()
    uploaded = client.post(
        "/api/v1/admin/import",
        files={"file": ("cat.xlsx", path.read_bytes(), XLSX_MIME)},
        headers=admin_headers(settings),
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["status"] == "applied"


def test_catalog_requires_init_data(tmp_path: Path) -> None:
    client, settings, factory, engine = _client(tmp_path)
    try:
        missing = client.get("/api/v1/search", params={"q": "цемент"})
        assert missing.status_code == 401
        tampered = make_init_data(settings.bot_token, 555).replace("555", "777")
        bad = client.get(
            "/api/v1/search",
            params={"q": "цемент"},
            headers={"X-Telegram-Init-Data": tampered},
        )
        assert bad.status_code == 401
        foreign = make_init_data("9:other-token", 555)
        other = client.get(
            "/api/v1/search",
            params={"q": "цемент"},
            headers={"X-Telegram-Init-Data": foreign},
        )
        assert other.status_code == 401
        cart = client.post("/api/v1/cart/items", json={"sku": "CEM-M500", "qty": 1})
        assert cart.status_code == 401
    finally:
        _cleanup(engine)


def test_search_categories_pagination_and_empty_query(tmp_path: Path) -> None:
    client, settings, factory, engine = _client(tmp_path)
    try:
        rows = [
            ["CEM-M500", "Цемент М500", "450.00", 12, "Сухие смеси", "Мешок 50 кг", 10],
            ["SAND-01", "Песок речной", "80.00", 2, "Сыпучие", "", 20],
        ]
        for index in range(21):
            rows.append([f"BET-{index:02d}", f"Бетон {index}", "10.00", 5, "Бетон", "", 30 + index])
        _import_catalog(client, tmp_path, rows)
        web = init_data_headers(settings)
        empty = client.get("/api/v1/search", params={"q": "  "}, headers=web)
        assert empty.status_code == 200
        assert empty.json()["items"] == []
        assert empty.json()["reason"] == "empty_query"
        assert "Сухие смеси" in empty.json()["category_hints"]

        cats = client.get("/api/v1/categories", headers=web)
        names = [item["name"] for item in cats.json()["items"]]
        assert "Сухие смеси" in names
        assert "Сыпучие" in names

        found = client.get("/api/v1/search", params={"q": "цемент М500"}, headers=web)
        item = found.json()["items"][0]
        assert item["sku"] == "CEM-M500"
        assert item["price"] == "450.00"
        assert item["availability"] == "в наличии"

        page1 = client.get("/api/v1/search", params={"q": "бетон", "page": 1}, headers=web)
        assert page1.json()["page_size"] == 20
        assert len(page1.json()["items"]) == 20
        page2 = client.get("/api/v1/search", params={"q": "бетон", "page": 2}, headers=web)
        assert len(page2.json()["items"]) == 1
        eof = client.get("/api/v1/search", params={"q": "бетон", "page": 99}, headers=web)
        assert eof.json()["items"] == []
        low = client.get("/api/v1/search", params={"q": "бетон", "page": 0}, headers=web)
        assert low.json()["items"] == []
    finally:
        _cleanup(engine)


def test_cart_server_price_and_qty_rules(tmp_path: Path) -> None:
    client, settings, factory, engine = _client(tmp_path)
    try:
        _import_catalog(
            client,
            tmp_path,
            [
                ["CEM-M500", "Цемент М500", "450.00", 12, "Сухие смеси", "", 10, True],
                ["SAND-01", "Песок речной", "80.00", 2, "Сыпучие", "", 20, True],
                ["HIDE-1", "Скрытый цемент", "1.00", 5, "Сухие смеси", "", 1, False],
            ],
            headers=["sku", "name", "price", "stock", "category", "description", "sort", "active"],
        )
        web = init_data_headers(settings, 555)
        spoof = client.post(
            "/api/v1/cart/items",
            headers=web,
            json={"sku": "CEM-M500", "qty": 2, "price": "0.01", "telegram_id": 1},
        )
        assert spoof.status_code == 200
        body = spoof.json()
        assert body["items"][0]["price"] == "450.00"
        assert body["items"][0]["line_total"] == "900.00"
        assert body["total"] == "900.00"

        other = init_data_headers(settings, 777)
        alien = client.get("/api/v1/cart", headers=other)
        assert alien.json()["items"] == []

        own = client.get("/api/v1/cart", headers=web)
        assert own.json()["total"] == "900.00"

        zero = client.post(
            "/api/v1/cart/items", headers=web, json={"sku": "SAND-01", "qty": 0}
        )
        assert zero.status_code == 400
        neg = client.post(
            "/api/v1/cart/items", headers=web, json={"sku": "SAND-01", "qty": -1}
        )
        assert neg.status_code == 400
        over = client.post(
            "/api/v1/cart/items", headers=web, json={"sku": "SAND-01", "qty": 999999}
        )
        assert over.status_code == 400
        hidden = client.post(
            "/api/v1/cart/items", headers=web, json={"sku": "HIDE-1", "qty": 1}
        )
        assert hidden.status_code == 400

        client.put("/api/v1/cart/items/SAND-01", headers=web, json={"sku": "SAND-01", "qty": 2})
        removed = client.delete("/api/v1/cart/items/SAND-01", headers=web)
        skus = [item["sku"] for item in removed.json()["items"]]
        assert "SAND-01" not in skus
        assert removed.json()["total"] == "900.00"
    finally:
        _cleanup(engine)


def test_blocked_user_search_and_cart_write(tmp_path: Path) -> None:
    client, settings, factory, engine = _client(tmp_path)
    try:
        _import_catalog(
            client,
            tmp_path,
            [["CEM-M500", "Цемент М500", "450.00", 12, "Сухие смеси", "", 10]],
        )
        web = init_data_headers(settings, 555)
        client.get("/api/v1/search", params={"q": "цемент"}, headers=web)

        async def _block() -> None:
            async with factory() as session:
                await session.execute(
                    update(User).where(User.telegram_id == 555).values(status="blocked")
                )
                await session.commit()

        asyncio.run(_block())
        search = client.get("/api/v1/search", params={"q": "цемент"}, headers=web)
        assert search.status_code == 200
        assert search.json()["items"] == []
        assert search.json()["reason"] == "user_blocked"
        write = client.post(
            "/api/v1/cart/items", headers=web, json={"sku": "CEM-M500", "qty": 1}
        )
        assert write.status_code == 403
        cart = client.get("/api/v1/cart", headers=web)
        assert cart.status_code == 403
    finally:
        _cleanup(engine)


def test_miniapp_html_is_russian_storefront() -> None:
    html = (APP_DIR / "index.html").read_text(encoding="utf-8")
    css = (APP_DIR / "app.css").read_text(encoding="utf-8")
    js = (APP_DIR / "app.js").read_text(encoding="utf-8")
    blob = html + css + js
    assert "Поиск" in html
    assert "Корзина" in html
    assert "Оформить" in blob
    assert "Мои заказы" in blob
    assert "TODO" not in blob
    assert "Coming soon" not in blob
    assert "/api/v1/checkout" in js
    assert "overflow-x: hidden" in css
    client = TestClient(app)
    page = client.get("/app/")
    assert page.status_code == 200
    assert "Прайс" in page.text
