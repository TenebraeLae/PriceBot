from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import TypeVar

from pricebot.domain.photo import resolve_product_photo

T = TypeVar("T")

MAX_QUERY_LEN = 200


def catalog_search_blob(name: str, sku: str, category: str = "") -> str:
    return " ".join(part for part in (name, sku, category) if part).casefold()


@dataclass(frozen=True)
class CatalogProduct:
    sku: str
    name: str
    category: str = ""
    description: str = ""
    price: Decimal = Decimal("0")
    stock: Decimal = Decimal("0")
    unit: str = "шт"
    photo_url: str | None = None
    active: bool = True
    sort: int = 0


@dataclass(frozen=True)
class SearchPage:
    items: list[CatalogProduct]
    page: int
    page_size: int
    total: int
    reason: str | None = None
    hint: str | None = None
    category_hints: tuple[str, ...] = ()


def availability_label(stock: Decimal) -> str:
    return "в наличии" if stock > 0 else "нет"


def product_card(product: CatalogProduct) -> dict[str, object]:
    return {
        "sku": product.sku,
        "name": product.name,
        "category": product.category,
        "description": product.description,
        "price": product.price,
        "stock": product.stock,
        "unit": product.unit,
        "photo_url": resolve_product_photo(product.photo_url),
        "availability": availability_label(product.stock),
    }


def paginate(items: Sequence[T], page: int, page_size: int) -> list[T]:
    if page < 1 or page_size < 1:
        return []
    start = (page - 1) * page_size
    if start >= len(items):
        return []
    return list(items[start : start + page_size])


def search_products(
    products: Sequence[CatalogProduct],
    query: str,
    *,
    page: int = 1,
    page_size: int = 10,
    user_status: str = "active",
    categories: Sequence[str] | None = None,
) -> SearchPage:
    hints = tuple(categories or ())
    if user_status == "blocked":
        return SearchPage(
            items=[],
            page=page,
            page_size=page_size,
            total=0,
            reason="user_blocked",
            hint="Поиск недоступен",
        )
    stripped = query.strip()
    if not stripped:
        return SearchPage(
            items=[],
            page=page,
            page_size=page_size,
            total=0,
            reason="empty_query",
            hint="Введите запрос",
            category_hints=hints,
        )
    if len(stripped) > MAX_QUERY_LEN:
        return SearchPage(
            items=[],
            page=page,
            page_size=page_size,
            total=0,
            reason="query_too_long",
        )

    needle = stripped.casefold()
    matched = [
        item
        for item in products
        if item.active
        and (
            needle in item.name.casefold()
            or needle in item.sku.casefold()
            or needle in item.category.casefold()
        )
    ]
    matched.sort(key=lambda item: (item.sort, item.sku))
    return SearchPage(
        items=paginate(matched, page, page_size),
        page=page,
        page_size=page_size,
        total=len(matched),
        reason="ok",
    )
