from decimal import Decimal
from pathlib import Path

from pricebot.db.models import Product
from pricebot.domain.catalog import catalog_search_blob
from pricebot.services.import_catalog import apply_price_import
from pricebot.services.search import get_product_card, search_products_db
from tests.conftest import write_xlsx


class BoomSession:
    async def execute(self, *_args, **_kwargs):
        raise AssertionError("must not scan catalog")

    async def scalar(self, *_args, **_kwargs):
        raise AssertionError("must not scan catalog")


def _blob_product(sku: str, name: str, sort: int) -> Product:
    return Product(
        sku=sku,
        name=name,
        price=Decimal("1"),
        stock=Decimal("1"),
        sort=sort,
        active=True,
        search_blob=catalog_search_blob(name, sku),
    )


async def _seed_cement(session, settings, tmp_path: Path) -> None:
    path = tmp_path / "cat.xlsx"
    write_xlsx(
        path,
        ["sku", "name", "price", "stock", "category", "description", "sort", "active"],
        [
            ["CEM-M500", "Цемент М500", "450.00", 12, "Сухие смеси", "Мешок 50 кг", 10, True],
            ["SAND-01", "Песок речной", "80.00", 2, "Сыпучие", "", 20, True],
            ["HIDE-1", "Скрытый цемент", "1.00", 5, "Сухие смеси", "", 1, False],
        ],
    )
    await apply_price_import(
        session,
        content=path.read_bytes(),
        filename="cat.xlsx",
        admin_id=1001,
        admin_ids=settings.admin_ids,
        imports_dir=settings.imports_dir,
    )


async def test_empty_and_blocked_and_long_do_not_query_products() -> None:
    blocked = await search_products_db(BoomSession(), "цемент", user_status="blocked")
    assert blocked.reason == "user_blocked"
    long = await search_products_db(BoomSession(), "ц" * 201)
    assert long.reason == "query_too_long"
    low = await search_products_db(BoomSession(), "цемент", page=0)
    assert low.items == []
    assert low.reason == "ok"


async def test_empty_query_does_not_read_xlsx(
    db_session, test_settings, tmp_path: Path, monkeypatch
) -> None:
    await _seed_cement(db_session, test_settings, tmp_path)

    def boom(*_args, **_kwargs):
        raise AssertionError("xlsx must not be opened")

    monkeypatch.setattr("pricebot.domain.excel.load_workbook", boom)
    page = await search_products_db(db_session, "   ")
    assert page.reason == "empty_query"
    assert page.items == []
    assert "Сухие смеси" in page.category_hints


async def test_search_cement_from_db_only(
    db_session, test_settings, tmp_path: Path, monkeypatch
) -> None:
    await _seed_cement(db_session, test_settings, tmp_path)

    def boom(*_args, **_kwargs):
        raise AssertionError("xlsx must not be opened")

    monkeypatch.setattr("pricebot.domain.excel.load_workbook", boom)
    page = await search_products_db(db_session, "цемент М500", page_size=test_settings.page_size)
    assert [item.sku for item in page.items] == ["CEM-M500"]
    assert page.items[0].price == Decimal("450.00")


async def test_like_wildcards_are_literals(db_session, test_settings, tmp_path: Path) -> None:
    await _seed_cement(db_session, test_settings, tmp_path)
    injection = await search_products_db(db_session, "%' OR 1=1")
    assert injection.items == []
    db_session.add(
        Product(
            sku="%' OR 1=1",
            name="Метка",
            price=Decimal("1"),
            stock=Decimal("1"),
            active=True,
            sort=0,
            search_blob=catalog_search_blob("Метка", "%' OR 1=1"),
        )
    )
    await db_session.commit()
    marked = await search_products_db(db_session, "%' OR 1=1")
    assert [item.sku for item in marked.items] == ["%' OR 1=1"]


async def test_inactive_hidden_and_pagination(
    db_session, test_settings, tmp_path: Path
) -> None:
    await _seed_cement(db_session, test_settings, tmp_path)
    hidden = await search_products_db(db_session, "скрытый")
    assert hidden.items == []
    eof = await search_products_db(db_session, "е", page=99, page_size=1)
    assert eof.items == []
    assert eof.total >= 1


async def test_order_sort_then_sku(db_session) -> None:
    db_session.add_all(
        [
            _blob_product("B", "бетон", 2),
            _blob_product("A", "бетон", 2),
            _blob_product("C", "бетон", 1),
        ]
    )
    await db_session.commit()
    page = await search_products_db(db_session, "бетон")
    assert [item.sku for item in page.items] == ["C", "A", "B"]


async def test_card_without_photo_from_db(db_session, test_settings, tmp_path: Path) -> None:
    await _seed_cement(db_session, test_settings, tmp_path)
    card = await get_product_card(db_session, "CEM-M500")
    assert card is not None
    assert card["photo_url"] is None
    assert card["price"] == Decimal("450.00")
    assert card["availability"] == "в наличии"
    assert await get_product_card(db_session, "HIDE-1") is None
