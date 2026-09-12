from datetime import datetime
from decimal import Decimal

import pytest

from pricebot.domain.access import ensure_admin
from pricebot.domain.cart import add_to_cart
from pricebot.domain.catalog import CatalogProduct
from pricebot.domain.checkout import StockBook, checkout, format_order_number, moscow_today
from pricebot.domain.errors import DomainError
from pricebot.domain.payments import OrderStatus
from pricebot.domain.promo import PromoKind, PromoSpec


def test_order_number_format(now: datetime) -> None:
    assert format_order_number(moscow_today(now), 1) == "PB-20260912-0001"
    assert format_order_number(moscow_today(now), 12) == "PB-20260912-0012"


def test_checkout_server_price_not_client(
    cement: CatalogProduct, now: datetime
) -> None:
    items = [add_to_cart(cement, 2)]
    draft = checkout(
        user_id=1,
        user_status="active",
        items=items,
        daily_seq=1,
        now=now,
        client_prices={"CEM-M500": Decimal("1.00")},
    )
    assert draft.total == Decimal("900.00")
    assert draft.items[0].price_snapshot == Decimal("450.00")
    assert draft.status is OrderStatus.awaiting_payment
    assert draft.number == "PB-20260912-0001"


def test_blocked_user_cannot_checkout(cement: CatalogProduct, now: datetime) -> None:
    with pytest.raises(DomainError) as err:
        checkout(
            user_id=1,
            user_status="blocked",
            items=[add_to_cart(cement, 1)],
            daily_seq=1,
            now=now,
        )
    assert err.value.code == "user_blocked"


def test_parallel_checkout_does_not_oversell(sand: CatalogProduct, now: datetime) -> None:
    book = StockBook({sand.sku: sand.stock})
    first = checkout(
        user_id=1,
        user_status="active",
        items=[add_to_cart(sand, 2)],
        daily_seq=1,
        now=now,
        stock=book,
    )
    assert first.total == Decimal("160.00")
    with pytest.raises(DomainError) as err:
        checkout(
            user_id=2,
            user_status="active",
            items=[add_to_cart(sand, 1)],
            daily_seq=2,
            now=now,
            stock=book,
        )
    assert err.value.code == "insufficient_stock"


def test_promo_on_checkout_and_non_admin(
    cement: CatalogProduct, now: datetime
) -> None:
    promo = PromoSpec(
        code="FIX",
        kind=PromoKind.fixed,
        value=Decimal("1000"),
        starts_at=now,
        ends_at=now,
        active=True,
    )
    draft = checkout(
        user_id=1,
        user_status="active",
        items=[add_to_cart(cement, 1)],
        daily_seq=3,
        now=now,
        promo=promo,
    )
    assert draft.total == Decimal("0.00")
    assert draft.promo_code == "FIX"
    with pytest.raises(DomainError) as err:
        ensure_admin(99, [1, 2])
    assert err.value.code == "forbidden"


def test_empty_cart_checkout_rejected(now: datetime) -> None:
    with pytest.raises(DomainError) as err:
        checkout(
            user_id=1,
            user_status="active",
            items=[],
            daily_seq=1,
            now=now,
        )
    assert err.value.code == "empty_cart"


def test_invalid_promo_on_checkout_refuses(cement: CatalogProduct, now: datetime) -> None:
    promo = PromoSpec(
        code="OLD",
        kind=PromoKind.percent,
        value=Decimal("10"),
        starts_at=now,
        ends_at=now,
        active=False,
    )
    with pytest.raises(DomainError) as err:
        checkout(
            user_id=1,
            user_status="active",
            items=[add_to_cart(cement, 1)],
            daily_seq=1,
            now=now,
            promo=promo,
        )
    assert err.value.code == "promo_inactive"


def test_checkout_without_shared_book_still_respects_product_stock(
    sand: CatalogProduct, now: datetime
) -> None:
    line = add_to_cart(sand, 2)
    with pytest.raises(DomainError) as err:
        checkout(
            user_id=1,
            user_status="active",
            items=[line, line],
            daily_seq=1,
            now=now,
        )
    assert err.value.code == "insufficient_stock"
