from decimal import Decimal

import pytest

from pricebot.domain.cart import add_to_cart, cart_subtotal
from pricebot.domain.catalog import CatalogProduct
from pricebot.domain.errors import DomainError


def test_qty_zero_and_negative_rejected(sand: CatalogProduct) -> None:
    with pytest.raises(DomainError) as zero:
        add_to_cart(sand, 0)
    with pytest.raises(DomainError) as neg:
        add_to_cart(sand, -1)
    assert zero.value.code == "invalid_qty"
    assert neg.value.code == "invalid_qty"


def test_qty_over_stock_rejected(sand: CatalogProduct) -> None:
    with pytest.raises(DomainError) as over:
        add_to_cart(sand, 999999)
    assert over.value.code == "qty_exceeds_stock"


def test_inactive_cannot_add(hidden: CatalogProduct) -> None:
    with pytest.raises(DomainError) as err:
        add_to_cart(hidden, 1)
    assert err.value.code == "inactive_sku"


def test_subtotal_uses_server_price(cement: CatalogProduct, sand: CatalogProduct) -> None:
    items = [add_to_cart(cement, 2), add_to_cart(sand, 2)]
    assert cart_subtotal(items) == Decimal("1060.00")
