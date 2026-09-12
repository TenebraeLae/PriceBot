from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from pricebot.domain.access import ensure_active_user
from pricebot.domain.cart import CartLine, as_qty, cart_subtotal, validate_cart_qty
from pricebot.domain.catalog import CatalogProduct
from pricebot.domain.errors import DomainError
from pricebot.domain.payments import OrderStatus
from pricebot.domain.promo import PromoSpec, apply_promo

MOSCOW = ZoneInfo("Europe/Moscow")


@dataclass(frozen=True)
class OrderLine:
    sku: str
    name: str
    qty: Decimal
    price_snapshot: Decimal


@dataclass(frozen=True)
class OrderDraft:
    number: str
    user_id: int
    items: tuple[OrderLine, ...]
    total: Decimal
    promo_code: str | None
    status: OrderStatus = OrderStatus.awaiting_payment


class StockBook:
    def __init__(self, stock: Mapping[str, Decimal]) -> None:
        self._stock: MutableMapping[str, Decimal] = dict(stock)

    def available(self, sku: str) -> Decimal:
        return self._stock.get(sku, Decimal("0"))

    def reserve(self, sku: str, qty: Decimal | int | str) -> None:
        amount = as_qty(qty)
        have = self.available(sku)
        if amount > have:
            raise DomainError("insufficient_stock", "Недостаточно остатка")
        self._stock[sku] = have - amount


def moscow_today(now: datetime | None = None) -> date:
    current = now or datetime.now(MOSCOW)
    if current.tzinfo is None:
        current = current.replace(tzinfo=MOSCOW)
    else:
        current = current.astimezone(MOSCOW)
    return current.date()


def format_order_number(on_date: date, seq: int) -> str:
    if seq < 1:
        raise DomainError("invalid_seq", "Номер заказа должен быть положительным")
    return f"PB-{on_date:%Y%m%d}-{seq:04d}"


def checkout(
    *,
    user_id: int,
    user_status: str,
    items: list[CartLine],
    daily_seq: int,
    now: datetime,
    promo: PromoSpec | None = None,
    stock: StockBook | None = None,
    client_prices: Mapping[str, Decimal] | None = None,
) -> OrderDraft:
    del client_prices  # Mini App prices are ignored; server price only
    ensure_active_user(user_status)
    if not items:
        raise DomainError("empty_cart", "Корзина пуста")

    book = stock or StockBook({item.product.sku: item.product.stock for item in items})
    lines: list[OrderLine] = []
    for item in items:
        product: CatalogProduct = item.product
        validate_cart_qty(product, item.qty)
        book.reserve(product.sku, item.qty)
        lines.append(
            OrderLine(
                sku=product.sku,
                name=product.name,
                qty=item.qty,
                price_snapshot=product.price,
            )
        )

    subtotal = cart_subtotal(items)
    promo_code = None
    total = subtotal
    if promo is not None:
        total = apply_promo(subtotal, promo, now=now)
        promo_code = promo.code

    return OrderDraft(
        number=format_order_number(moscow_today(now), daily_seq),
        user_id=user_id,
        items=tuple(lines),
        total=total,
        promo_code=promo_code,
    )
