import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy import func, select, update

from pricebot.db.models import Order, Payment, Product, User
from pricebot.domain.payments import dumps_webhook, sign_payload
from pricebot.services.notify import get_notification_log, reset_notifications
from tests.conftest import init_data_headers
from tests.test_miniapp_api import _cleanup, _client, _import_catalog


def _png(data: str) -> bytes:
    return base64.b64decode(data)


def _seed_catalog(client, tmp_path: Path) -> None:
    _import_catalog(
        client,
        tmp_path,
        [
            ["CEM-M500", "Цемент М500", "450.00", 12, "Сухие смеси", "", 10],
            ["SAND-01", "Песок речной", "80.00", 1, "Сыпучие", "", 20],
        ],
    )


def _checkout(client, settings, telegram_id: int = 555, extra: dict | None = None):
    return client.post(
        "/api/v1/checkout",
        headers=init_data_headers(settings, telegram_id),
        json=extra or {"telegram_id": 1, "price": "0.01"},
    )


def test_checkout_qr_and_hmac_on_new_routes(tmp_path: Path) -> None:
    client, settings, factory, engine = _client(tmp_path)
    reset_notifications()
    try:
        _seed_catalog(client, tmp_path)
        web = init_data_headers(settings, 555)
        assert client.post("/api/v1/checkout", json={"sku": "CEM-M500"}).status_code == 401
        assert client.get("/api/v1/orders").status_code == 401
        assert client.get("/api/v1/orders/PB-1/qr").status_code == 401

        added = client.post("/api/v1/cart/items", headers=web, json={"sku": "CEM-M500", "qty": 1})
        assert added.status_code == 200
        paid = _checkout(client, settings, 555)
        assert paid.status_code == 200
        body = paid.json()
        assert body["number"].startswith("PB-")
        assert body["amount"] == "450.00"
        assert body["payload"].startswith("https://pay.local/")
        png = _png(body["qr_png_base64"])
        assert len(png) > 0
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        assert body["status"] == "awaiting_payment"
        assert body["status_label"] == "ожидает оплаты"

        async def _state() -> tuple[int, int, object, object]:
            async with factory() as session:
                orders = (await session.execute(select(func.count()).select_from(Order))).scalar_one()
                pays = (await session.execute(select(func.count()).select_from(Payment))).scalar_one()
                order = (await session.execute(select(Order))).scalar_one()
                stock = (
                    await session.execute(select(Product.stock).where(Product.sku == "CEM-M500"))
                ).scalar_one()
                return orders, pays, order.status, stock

        orders, pays, status, stock = asyncio.run(_state())
        assert orders == 1
        assert pays == 1
        assert status == "awaiting_payment"
        assert stock == 11
        assert get_notification_log().count(kind="order_created") == 1
    finally:
        _cleanup(engine)


def test_checkout_refuses_negative_stock_no_order(tmp_path: Path) -> None:
    client, settings, factory, engine = _client(tmp_path)
    try:
        _seed_catalog(client, tmp_path)
        web = init_data_headers(settings, 555)
        client.post("/api/v1/cart/items", headers=web, json={"sku": "CEM-M500", "qty": 2})

        async def _drop() -> None:
            async with factory() as session:
                await session.execute(
                    update(Product).where(Product.sku == "CEM-M500").values(stock=1)
                )
                await session.commit()

        asyncio.run(_drop())
        refused = _checkout(client, settings, 555)
        assert refused.status_code == 400

        async def _count() -> int:
            async with factory() as session:
                return (await session.execute(select(func.count()).select_from(Order))).scalar_one()

        assert asyncio.run(_count()) == 0
        cart = client.get("/api/v1/cart", headers=web)
        assert cart.json()["items"]
    finally:
        _cleanup(engine)


def test_unique_numbers_and_single_payment_double_tap(tmp_path: Path) -> None:
    client, settings, factory, engine = _client(tmp_path)
    try:
        _seed_catalog(client, tmp_path)
        web = init_data_headers(settings, 555)
        client.post("/api/v1/cart/items", headers=web, json={"sku": "CEM-M500", "qty": 1})
        first = _checkout(client, settings, 555)
        client.post("/api/v1/cart/items", headers=web, json={"sku": "CEM-M500", "qty": 1})
        second = _checkout(client, settings, 555)
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["number"] != second.json()["number"]

        client.post("/api/v1/cart/items", headers=web, json={"sku": "CEM-M500", "qty": 1})
        third = _checkout(client, settings, 555)
        empty = _checkout(client, settings, 555)
        assert third.status_code == 200
        assert empty.status_code == 400

        async def _pays() -> int:
            async with factory() as session:
                return (await session.execute(select(func.count()).select_from(Payment))).scalar_one()

        assert asyncio.run(_pays()) == 3
    finally:
        _cleanup(engine)


def test_two_checkouts_do_not_oversell(tmp_path: Path) -> None:
    client, settings, factory, engine = _client(tmp_path)
    try:
        _seed_catalog(client, tmp_path)
        client.post(
            "/api/v1/cart/items",
            headers=init_data_headers(settings, 555),
            json={"sku": "SAND-01", "qty": 1},
        )
        client.post(
            "/api/v1/cart/items",
            headers=init_data_headers(settings, 777),
            json={"sku": "SAND-01", "qty": 1},
        )
        a = _checkout(client, settings, 555)
        b = _checkout(client, settings, 777)
        assert a.status_code == 200
        assert b.status_code == 400

        def _one(uid: int):
            return _checkout(client, settings, uid)

        client.post(
            "/api/v1/cart/items",
            headers=init_data_headers(settings, 888),
            json={"sku": "CEM-M500", "qty": 1},
        )
        client.post(
            "/api/v1/cart/items",
            headers=init_data_headers(settings, 999),
            json={"sku": "CEM-M500", "qty": 1},
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(_one, [888, 999]))
        codes = sorted(item.status_code for item in results)
        assert 200 in codes

        async def _sand() -> object:
            async with factory() as session:
                stock = (
                    await session.execute(select(Product.stock).where(Product.sku == "SAND-01"))
                ).scalar_one()
                orders = (await session.execute(select(func.count()).select_from(Order))).scalar_one()
                return stock, orders

        stock, orders = asyncio.run(_sand())
        assert stock == 0
        assert orders >= 1
    finally:
        _cleanup(engine)


def test_webhook_paid_replay_bad_sig_mismatch_and_no_webhook(tmp_path: Path) -> None:
    client, settings, factory, engine = _client(tmp_path)
    reset_notifications()
    try:
        _seed_catalog(client, tmp_path)
        web = init_data_headers(settings, 555)
        client.post("/api/v1/cart/items", headers=web, json={"sku": "CEM-M500", "qty": 1})
        created = _checkout(client, settings, 555)
        number = created.json()["number"]
        payload = created.json()["payload"]
        provider_payment_id = payload.rsplit("/", 1)[-1]

        listed = client.get("/api/v1/orders", headers=web)
        assert listed.status_code == 200
        assert listed.json()["items"][0]["status"] == "awaiting_payment"
        assert listed.json()["items"][0]["paid_at"] is None

        qr = client.get(f"/api/v1/orders/{number}/qr", headers=web)
        assert qr.status_code == 200
        assert qr.headers["content-type"].startswith("image/png")
        assert len(qr.content) > 0
        again = client.get(f"/api/v1/orders/{number}", headers=web)
        assert again.json()["payload"] == payload
        assert again.json()["qr_bytes"] > 0

        body = dumps_webhook(
            {"provider_payment_id": provider_payment_id, "amount": "450.00", "status": "succeeded"}
        )
        bad = client.post(
            "/api/v1/payments/webhook",
            content=body,
            headers={"Content-Type": "application/json", "X-Payment-Signature": "deadbeef"},
        )
        assert bad.status_code == 401

        async def _still_waiting() -> tuple[str, object]:
            async with factory() as session:
                order = (
                    await session.execute(select(Order).where(Order.number == number))
                ).scalar_one()
                return order.status, order.paid_at

        status, paid_at = asyncio.run(_still_waiting())
        assert status == "awaiting_payment"
        assert paid_at is None

        good_headers = {
            "Content-Type": "application/json",
            "X-Payment-Signature": sign_payload(body, settings.payment_webhook_secret),
        }
        ok = client.post("/api/v1/payments/fake/webhook", content=body, headers=good_headers)
        assert ok.status_code == 200
        assert ok.json()["order_status"] == "paid"
        assert ok.json()["noop"] is False
        first_paid_at = ok.json()["paid_at"]
        assert first_paid_at

        replay = client.post("/api/v1/payments/webhook", content=body, headers=good_headers)
        assert replay.status_code == 200
        assert replay.json()["noop"] is True
        assert replay.json()["order_status"] == "paid"
        assert replay.json()["paid_at"] == first_paid_at
        assert get_notification_log().count(kind="order_paid", order_number=number) == 1

        client.post("/api/v1/cart/items", headers=web, json={"sku": "CEM-M500", "qty": 1})
        other = _checkout(client, settings, 555)
        other_pid = other.json()["payload"].rsplit("/", 1)[-1]
        mismatch_body = dumps_webhook(
            {"provider_payment_id": other_pid, "amount": "1.00", "status": "succeeded"}
        )
        mismatch = client.post(
            "/api/v1/payments/webhook",
            content=mismatch_body,
            headers={
                "Content-Type": "application/json",
                "X-Payment-Signature": sign_payload(
                    mismatch_body, settings.payment_webhook_secret
                ),
            },
        )
        assert mismatch.status_code == 200
        assert mismatch.json()["order_status"] == "error"
        assert mismatch.json()["payment_status"] == "failed"
    finally:
        _cleanup(engine)


def test_spoof_and_blocked_cannot_checkout(tmp_path: Path) -> None:
    client, settings, factory, engine = _client(tmp_path)
    try:
        _seed_catalog(client, tmp_path)
        owner = init_data_headers(settings, 555)
        client.post("/api/v1/cart/items", headers=owner, json={"sku": "CEM-M500", "qty": 1})
        spoof = _checkout(client, settings, 777, extra={"telegram_id": 555, "price": "0.01"})
        assert spoof.status_code == 400
        own = client.get("/api/v1/cart", headers=owner)
        assert own.json()["items"]

        async def _block() -> None:
            async with factory() as session:
                await session.execute(
                    update(User).where(User.telegram_id == 555).values(status="blocked")
                )
                await session.commit()

        asyncio.run(_block())
        blocked = _checkout(client, settings, 555)
        assert blocked.status_code == 403
        orders = client.get("/api/v1/orders", headers=owner)
        assert orders.status_code == 403
    finally:
        _cleanup(engine)


def test_double_tap_checkout_one_order(tmp_path: Path) -> None:
    client, settings, factory, engine = _client(tmp_path)
    try:
        _seed_catalog(client, tmp_path)
        web = init_data_headers(settings, 555)
        client.post("/api/v1/cart/items", headers=web, json={"sku": "CEM-M500", "qty": 1})
        first = _checkout(client, settings, 555)
        second = _checkout(client, settings, 555)
        assert first.status_code == 200
        assert second.status_code == 400
        assert second.json()["detail"]

        async def _count() -> tuple[int, int]:
            async with factory() as session:
                orders = (await session.execute(select(func.count()).select_from(Order))).scalar_one()
                pays = (await session.execute(select(func.count()).select_from(Payment))).scalar_one()
                return int(orders), int(pays)

        assert asyncio.run(_count()) == (1, 1)
    finally:
        _cleanup(engine)


def test_miniapp_html_has_checkout_russian() -> None:
    from pricebot.web.main import APP_DIR, app
    from fastapi.testclient import TestClient

    html = (APP_DIR / "index.html").read_text(encoding="utf-8")
    js = (APP_DIR / "app.js").read_text(encoding="utf-8")
    blob = html + js
    assert "Оформить" in blob
    assert "Мои заказы" in blob
    assert "/api/v1/checkout" in js
    assert "/api/v1/orders" in js
    page = TestClient(app).get("/app/")
    assert page.status_code == 200
    assert "Оформить" in page.text
