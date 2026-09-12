from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from pricebot.domain.catalog import CatalogProduct
from pricebot.domain.errors import DomainError


def as_qty(value: Decimal | int | str) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


@dataclass(frozen=True)
class CartLine:
    product: CatalogProduct
    qty: Decimal

    @property
    def line_total(self) -> Decimal:
        return (self.qty * self.product.price).quantize(Decimal("0.01"))


def validate_cart_qty(product: CatalogProduct, qty: Decimal | int | str) -> Decimal:
    if not product.active:
        raise DomainError("inactive_sku", "Товар недоступен")
    amount = as_qty(qty)
    if amount <= 0:
        raise DomainError("invalid_qty", "Количество должно быть больше 0")
    if amount > product.stock:
        raise DomainError("qty_exceeds_stock", "Недостаточно остатка")
    return amount


def add_to_cart(product: CatalogProduct, qty: Decimal | int | str) -> CartLine:
    amount = validate_cart_qty(product, qty)
    return CartLine(product=product, qty=amount)


def cart_subtotal(items: Sequence[CartLine]) -> Decimal:
    total = sum((item.line_total for item in items), Decimal("0"))
    return total.quantize(Decimal("0.01"))
