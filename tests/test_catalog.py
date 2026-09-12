from decimal import Decimal

from pricebot.domain.catalog import (
    CatalogProduct,
    availability_label,
    catalog_search_blob,
    product_card,
    search_products,
)


class BoomCatalog:
    def __iter__(self):
        raise AssertionError("must not scan catalog")


def test_empty_query_does_not_scan() -> None:
    page = search_products(BoomCatalog(), "   ", categories=["Сухие смеси"])
    assert page.items == []
    assert page.reason == "empty_query"
    assert page.hint == "Введите запрос"
    assert page.category_hints == ("Сухие смеси",)


def test_query_too_long_does_not_scan() -> None:
    page = search_products(BoomCatalog(), "ц" * 201)
    assert page.items == []
    assert page.reason == "query_too_long"


def test_blocked_user_search_refuses() -> None:
    page = search_products(BoomCatalog(), "цемент", user_status="blocked")
    assert page.items == []
    assert page.reason == "user_blocked"


def test_search_substring_casefold(catalog: list[CatalogProduct]) -> None:
    page = search_products(catalog, "цемент м500")
    assert [item.sku for item in page.items] == ["CEM-M500"]


def test_search_by_sku_and_category(catalog: list[CatalogProduct]) -> None:
    assert search_products(catalog, "cem-m500").items[0].sku == "CEM-M500"
    assert search_products(catalog, "сыпучие").items[0].sku == "SAND-01"


def test_sql_like_query_is_literal(catalog: list[CatalogProduct]) -> None:
    marked = CatalogProduct(sku="%' OR 1=1", name="Метка", price=Decimal("1"), stock=Decimal("1"))
    page = search_products([*catalog, marked], "%' OR 1=1")
    assert [item.sku for item in page.items] == ["%' OR 1=1"]


def test_unknown_sku_empty(catalog: list[CatalogProduct]) -> None:
    page = search_products(catalog, "нет-такого-sku")
    assert page.items == []
    assert page.total == 0


def test_inactive_hidden(catalog: list[CatalogProduct]) -> None:
    page = search_products(catalog, "скрытый")
    assert page.items == []


def test_pagination_page_below_one_and_past_eof(catalog: list[CatalogProduct]) -> None:
    active = [item for item in catalog if item.active]
    low = search_products(active, "е", page=0, page_size=10)
    eof = search_products(active, "е", page=99, page_size=1)
    assert low.items == []
    assert eof.items == []


def test_stable_order_sort_then_sku() -> None:
    items = [
        CatalogProduct(sku="B", name="бетон", price=Decimal("1"), stock=Decimal("1"), sort=2),
        CatalogProduct(sku="A", name="бетон", price=Decimal("1"), stock=Decimal("1"), sort=2),
        CatalogProduct(sku="C", name="бетон", price=Decimal("1"), stock=Decimal("1"), sort=1),
    ]
    page = search_products(items, "бетон")
    assert [item.sku for item in page.items] == ["C", "A", "B"]


def test_card_without_photo_and_server_price(cement: CatalogProduct) -> None:
    card = product_card(cement)
    assert card["photo_url"] is None
    assert card["price"] == Decimal("450.00")
    assert card["availability"] == "в наличии"


def test_availability_zero_stock() -> None:
    assert availability_label(Decimal("0")) == "нет"


def test_search_blob_is_casefold() -> None:
    blob = catalog_search_blob("Цемент М500", "CEM-M500", "Сухие смеси")
    assert "цемент м500" in blob
    assert "cem-m500" in blob

