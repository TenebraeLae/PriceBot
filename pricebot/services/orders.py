from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pricebot.config import Settings
from pricebot.db.models import (
    Cart,
    CartItem,
    Category,
    Order,
    OrderItem,
    Payment,
    Product,
    PromoCode,
)
from pricebot.domain.access import ensure_active_user
from pricebot.domain.cart import CartLine
from pricebot.domain.checkout import MOSCOW, StockBook, checkout, format_order_number, moscow_today
from pricebot.domain.errors import DomainError
from pricebot.domain.payments import (
    FakePaymentProvider,
    OrderStatus,
    PaymentDraft,
    PaymentProvider,
    PaymentStatus,
    apply_payment_webhook,
    ensure_single_payment,
    order_status_label,
)
from pricebot.domain.yookassa import (
    YooKassaPaymentProvider,
    default_return_url,
    parse_trusted_ips,
)
from pricebot.domain.qr import render_qr
from pricebot.domain.promo import PromoKind, PromoSpec
from pricebot.services.notify import notify_order_created, notify_order_error, notify_order_paid
from pricebot.services.search import to_catalog_product


@dataclass(frozen=True)
class CheckoutResult:
    number: str
    amount: Decimal
    payload: str
    qr_png: bytes
    status: str
    promo_code: str | None = None


def payment_provider(settings: Settings) -> PaymentProvider:
    name = (settings.payment_provider or "fake").strip().lower()
    if name in {"", "fake"}:
        return FakePaymentProvider(secret=settings.payment_webhook_secret)
    if name == "yookassa":
        shop_id = settings.yookassa_shop_id.strip()
        secret = settings.yookassa_secret_key.strip()
        if not shop_id or not secret:
            raise DomainError("yookassa_config", "Не заданы YOOKASSA_SHOP_ID / YOOKASSA_SECRET_KEY")
        return YooKassaPaymentProvider(
            shop_id,
            secret,
            default_return_url(settings.public_base_url, settings.yookassa_return_url),
            trusted_ips=parse_trusted_ips(settings.yookassa_trusted_ips),
        )
    raise DomainError("unknown_payment_provider", "Неизвестный платёжный провайдер")


def payment_payload_url(payment: Payment) -> str:
    raw = (payment.raw_payload or "").strip()
    if raw.startswith("http"):
        return raw.split("\n", 1)[0]
    if payment.provider_payment_id:
        return f"https://pay.local/{payment.provider_payment_id}"
    raise DomainError("empty_qr_payload", "Пустой контур QR не пишется")


def _supports_for_update(session: AsyncSession) -> bool:
    bind = session.get_bind()
    return bind.dialect.name != "sqlite"


async def _lock_products(session: AsyncSession, skus: list[str]) -> dict[str, Product]:
    unique = sorted(set(skus))
    stmt = select(Product).where(Product.sku.in_(unique)).order_by(Product.sku.asc())
    if _supports_for_update(session):
        stmt = stmt.with_for_update()
    rows = await session.execute(stmt)
    found = {row.sku: row for row in rows.scalars().all()}
    missing = [sku for sku in unique if sku not in found]
    if missing:
        raise DomainError("sku_not_found", "Товар не найден")
    return found


async def _next_order_number(session: AsyncSession, now: datetime) -> str:
    day = moscow_today(now)
    prefix = f"PB-{day:%Y%m%d}-"
    result = await session.execute(
        select(Order.number)
        .where(Order.number.like(f"{prefix}%"))
        .order_by(Order.number.desc())
        .limit(1)
    )
    last = result.scalar_one_or_none()
    seq = 1
    if last is not None:
        seq = int(last.rsplit("-", 1)[1]) + 1
    return format_order_number(day, seq)


async def _load_cart_bundle(
    session: AsyncSession, telegram_id: int
) -> tuple[Cart | None, list[tuple[CartItem, Product, str]]]:
    cart_stmt = select(Cart).where(Cart.user_id == telegram_id)
    if _supports_for_update(session):
        cart_stmt = cart_stmt.with_for_update()
    cart_row = await session.execute(cart_stmt)
    cart = cart_row.scalar_one_or_none()
    if cart is None:
        return None, []
    rows = await session.execute(
        select(CartItem, Product, func.coalesce(Category.name, ""))
        .join(Product, CartItem.product_id == Product.id)
        .outerjoin(Category, Product.category_id == Category.id)
        .where(CartItem.cart_id == cart.id)
        .order_by(Product.sku.asc())
    )
    return cart, list(rows.all())



def _iso(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=MOSCOW)
    return moment.isoformat()


def _order_payload(order: Order, payment: Payment | None, *, include_qr: bool) -> dict[str, object]:
    body: dict[str, object] = {
        "number": order.number,
        "total": str(order.total),
        "amount": str(order.total),
        "status": order.status,
        "status_label": order_status_label(order.status),
        "promo_code": order.promo_code,
        "created_at": _iso(order.created_at),
        "paid_at": _iso(order.paid_at),
        "items": [
            {
                "sku": item.sku,
                "name": item.name,
                "qty": str(item.qty),
                "price_snapshot": str(item.price_snapshot),
            }
            for item in order.items
        ],
    }
    if payment is not None and order.status == OrderStatus.awaiting_payment.value:
        payload = payment_payload_url(payment)
        body["payload"] = payload
        if include_qr:
            image = render_qr(payload)
            body["qr_png_base64"] = base64.b64encode(image.png_bytes).decode("ascii")
            body["qr_bytes"] = len(image.png_bytes)
    return body



async def _resolve_checkout_promo(
    session: AsyncSession, code: str | None
) -> tuple[PromoSpec | None, PromoCode | None]:
    if not code or not str(code).strip():
        return None, None
    key = str(code).strip()
    stmt = select(PromoCode).where(func.lower(PromoCode.code) == key.casefold())
    if _supports_for_update(session):
        stmt = stmt.with_for_update()
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise DomainError("promo_invalid", "Промокод неверен")
    spec = PromoSpec(
        code=row.code,
        kind=PromoKind(row.kind),
        value=row.value,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        max_uses=row.max_uses,
        used_count=row.used_count,
        active=row.active,
    )
    return spec, row


async def checkout_cart(
    session: AsyncSession,
    *,
    user_id: int,
    user_status: str,
    settings: Settings,
    now: datetime | None = None,
    provider: PaymentProvider | None = None,
    promo_code: str | None = None,
) -> CheckoutResult:
    ensure_active_user(user_status)
    current = now or datetime.now(MOSCOW)
    cart, rows = await _load_cart_bundle(session, user_id)
    if cart is None or not rows:
        raise DomainError("empty_cart", "Корзина пуста")

    locked = await _lock_products(session, [product.sku for _, product, _ in rows])
    lines: list[CartLine] = []
    stock_map: dict[str, Decimal] = {}
    for item, product, category_name in rows:
        fresh = locked[product.sku]
        catalog = to_catalog_product(fresh, category_name)
        lines.append(CartLine(product=catalog, qty=item.qty))
        stock_map[fresh.sku] = fresh.stock

    promo_spec, promo_row = await _resolve_checkout_promo(session, promo_code)
    book = StockBook(stock_map)
    draft = checkout(
        user_id=user_id,
        user_status=user_status,
        items=lines,
        daily_seq=1,
        now=current,
        promo=promo_spec,
        stock=book,
    )

    factory = provider or payment_provider(settings)
    payment_draft: PaymentDraft | None = None
    order: Order | None = None
    for _ in range(8):
        number = await _next_order_number(session, current)
        order = Order(
            number=number,
            user_id=user_id,
            total=draft.total,
            promo_code=draft.promo_code,
            status=OrderStatus.awaiting_payment.value,
        )
        try:
            async with session.begin_nested():
                session.add(order)
                await session.flush()
            break
        except IntegrityError:
            order = None
            continue
    if order is None:
        raise DomainError("order_number", "Не удалось выдать номер заказа")

    for line in draft.items:
        session.add(
            OrderItem(
                order_id=order.id,
                sku=line.sku,
                name=line.name,
                qty=line.qty,
                price_snapshot=line.price_snapshot,
            )
        )

    payment_draft = ensure_single_payment(None, factory, order.number, draft.total)
    session.add(
        Payment(
            order_id=order.id,
            provider=payment_draft.provider,
            provider_payment_id=payment_draft.provider_payment_id,
            amount=payment_draft.amount,
            status=payment_draft.status.value,
            raw_payload=payment_draft.payload,
        )
    )

    for sku, product in locked.items():
        product.stock = book.available(sku)
        if product.stock < 0:
            raise DomainError("insufficient_stock", "Недостаточно остатка")

    await session.execute(delete(CartItem).where(CartItem.cart_id == cart.id))
    if promo_row is not None:
        promo_row.used_count = int(promo_row.used_count or 0) + 1
    await session.flush()

    qr = render_qr(payment_draft.payload)
    await session.commit()
    await notify_order_created(settings, user_id, order.number, str(order.total))
    return CheckoutResult(
        number=order.number,
        amount=order.total,
        payload=payment_draft.payload,
        qr_png=qr.png_bytes,
        status=order.status,
        promo_code=order.promo_code,
    )


async def list_user_orders(session: AsyncSession, user_id: int) -> list[Order]:
    result = await session.execute(
        select(Order)
        .where(Order.user_id == user_id)
        .order_by(Order.created_at.desc(), Order.id.desc())
    )
    return list(result.scalars().all())


async def get_user_order(session: AsyncSession, user_id: int, number: str) -> Order:
    result = await session.execute(
        select(Order).where(Order.user_id == user_id, Order.number == number)
    )
    order = result.scalar_one_or_none()
    if order is None:
        raise DomainError("order_not_found", "Заказ не найден")
    await session.refresh(order, attribute_names=["items", "payments"])
    return order


def first_payment(order: Order) -> Payment | None:
    if not order.payments:
        return None
    return order.payments[0]


async def order_json(
    session: AsyncSession, user_id: int, number: str, *, include_qr: bool
) -> dict[str, object]:
    order = await get_user_order(session, user_id, number)
    return _order_payload(order, first_payment(order), include_qr=include_qr)


def orders_json(orders: list[Order]) -> dict[str, object]:
    return {
        "items": [
            {
                "number": order.number,
                "total": str(order.total),
                "amount": str(order.total),
                "status": order.status,
                "status_label": order_status_label(order.status),
                "paid_at": _iso(order.paid_at),
                "created_at": _iso(order.created_at),
            }
            for order in orders
        ]
    }


async def qr_png_for_order(session: AsyncSession, user_id: int, number: str) -> bytes:
    order = await get_user_order(session, user_id, number)
    if order.status != OrderStatus.awaiting_payment.value:
        raise DomainError("qr_unavailable", "QR недоступен")
    payment = first_payment(order)
    if payment is None:
        raise DomainError("qr_unavailable", "QR недоступен")
    return render_qr(payment_payload_url(payment)).png_bytes


def checkout_json(result: CheckoutResult) -> dict[str, object]:
    return {
        "number": result.number,
        "amount": str(result.amount),
        "total": str(result.amount),
        "payload": result.payload,
        "qr_png_base64": base64.b64encode(result.qr_png).decode("ascii"),
        "qr_bytes": len(result.qr_png),
        "status": result.status,
        "status_label": order_status_label(result.status),
        "promo_code": result.promo_code,
    }


async def apply_webhook_bytes(
    session: AsyncSession,
    *,
    settings: Settings,
    body: bytes,
    signature: str,
    client_ip: str = "",
    provider: PaymentProvider | None = None,
) -> dict[str, object]:
    factory = provider or payment_provider(settings)
    notify_check = getattr(factory, "verify_notification", None)
    if callable(notify_check):
        if not notify_check(client_ip, body):
            return {"http_status": 401, "detail": "Недействительное уведомление платежа"}
    elif not factory.verify_signature(body, signature or ""):
        return {"http_status": 401, "detail": "Недействительная подпись платежа"}
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DomainError("bad_webhook", "Некорректное тело webhook") from exc
    event = factory.parse_webhook(parsed)

    result = await session.execute(
        select(Payment).where(Payment.provider_payment_id == event.provider_payment_id)
    )
    payment = result.scalar_one_or_none()
    if payment is None:
        raise DomainError("payment_not_found", "Платёж не найден")
    order = await session.get(Order, payment.order_id)
    if order is None:
        raise DomainError("order_not_found", "Заказ не найден")

    seen: set[str] = set()
    if payment.status in {PaymentStatus.succeeded.value, PaymentStatus.failed.value}:
        seen.add(event.provider_payment_id)

    applied = apply_payment_webhook(
        order_status=OrderStatus(order.status),
        order_total=order.total,
        payment_status=PaymentStatus(payment.status),
        event=event,
        signature_valid=True,
        seen_ids=seen,
    )
    if applied.noop:
        return {
            "http_status": 200,
            "ok": True,
            "noop": True,
            "order_status": order.status,
            "payment_status": payment.status,
            "paid_at": _iso(order.paid_at),
        }

    payment.status = applied.payment_status.value
    payment.raw_payload = payment_payload_url(payment)
    order.status = applied.order_status.value
    if applied.order_status is OrderStatus.paid:
        order.paid_at = datetime.now(MOSCOW)
        await session.commit()
        await notify_order_paid(settings, order.user_id, order.number)
    elif applied.order_status is OrderStatus.error:
        await session.commit()
        await notify_order_error(settings, order.user_id, order.number)
    else:
        await session.commit()

    return {
        "http_status": 200,
        "ok": True,
        "noop": False,
        "order_status": order.status,
        "payment_status": payment.status,
        "paid_at": _iso(order.paid_at),
    }


def format_orders_list(orders: list[Order]) -> str:
    if not orders:
        return "Заказов пока нет."
    lines = [
        f"{order.number} · {order.total} ₽ · {order_status_label(order.status)}"
        for order in orders
    ]
    return "\n".join(lines)
