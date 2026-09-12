from pathlib import Path

from sqlalchemy import func, select

from pricebot.db.models import Product
from pricebot.domain.errors import DomainError
from pricebot.services.import_catalog import apply_price_import
from tests.conftest import write_xlsx

HEADERS = ["sku", "name", "price", "stock", "category", "description"]


async def _count_sku(session, sku: str) -> int:
    return int(
        await session.scalar(select(func.count()).select_from(Product).where(Product.sku == sku))
        or 0
    )


async def test_applied_rebuilds_active_catalog(
    db_session, test_settings, tmp_path: Path
) -> None:
    old = tmp_path / "old.xlsx"
    write_xlsx(old, HEADERS, [["OLD-1", "Старый", 10, 1, "Прочее", ""]])
    first = await apply_price_import(
        db_session,
        content=old.read_bytes(),
        filename="old.xlsx",
        admin_id=1001,
        admin_ids=test_settings.admin_ids,
        imports_dir=test_settings.imports_dir,
    )
    assert first.status == "applied"
    assert await _count_sku(db_session, "OLD-1") == 1

    fresh = tmp_path / "fresh.xlsx"
    write_xlsx(
        fresh,
        HEADERS,
        [["CEM-M500", "Цемент М500", "450.00", 12, "Сухие смеси", "Мешок 50 кг"]],
    )
    report = await apply_price_import(
        db_session,
        content=fresh.read_bytes(),
        filename="fresh.xlsx",
        admin_id=1001,
        admin_ids=test_settings.admin_ids,
        imports_dir=test_settings.imports_dir,
    )
    assert report.status == "applied"
    assert report.rows_ok == 1
    assert list(Path(test_settings.imports_dir).glob("*.xlsx"))
    assert await _count_sku(db_session, "OLD-1") == 0
    product = (await db_session.execute(select(Product).where(Product.sku == "CEM-M500"))).scalar_one()
    assert product.name == "Цемент М500"
    assert product.import_id == report.import_id


async def test_rejected_import_keeps_old_products(
    db_session, test_settings, tmp_path: Path
) -> None:
    seed = tmp_path / "seed.xlsx"
    write_xlsx(seed, HEADERS, [["KEEP-1", "Оставить", 5, 2, "", ""]])
    await apply_price_import(
        db_session,
        content=seed.read_bytes(),
        filename="seed.xlsx",
        admin_id=1001,
        admin_ids=test_settings.admin_ids,
        imports_dir=test_settings.imports_dir,
    )

    for name, payload in (
        ("empty.xlsx", b""),
        ("headers.xlsx", None),
        ("zero.xlsx", None),
        ("garbage.xlsx", b"not-an-excel"),
    ):
        path = tmp_path / name
        if name == "headers.xlsx":
            write_xlsx(path, ["foo", "bar"], [["a", "b"]])
        elif name == "zero.xlsx":
            write_xlsx(path, ["sku", "name", "price"], [["A", "Товар", "бесплатно"]])
        elif payload is not None:
            path.write_bytes(payload)
        report = await apply_price_import(
            db_session,
            content=path.read_bytes(),
            filename=name,
            admin_id=1001,
            admin_ids=test_settings.admin_ids,
            imports_dir=test_settings.imports_dir,
        )
        assert report.status == "rejected"
        assert await _count_sku(db_session, "KEEP-1") == 1


async def test_non_admin_cannot_import(db_session, test_settings, tmp_path: Path) -> None:
    path = tmp_path / "x.xlsx"
    write_xlsx(path, HEADERS, [["A", "Товар", 1, 1, "", ""]])
    try:
        await apply_price_import(
            db_session,
            content=path.read_bytes(),
            filename="x.xlsx",
            admin_id=9,
            admin_ids=test_settings.admin_ids,
            imports_dir=test_settings.imports_dir,
        )
    except DomainError as exc:
        assert exc.code == "forbidden"
    else:
        raise AssertionError("expected forbidden")


async def test_partial_file_applies_only_valid_rows(
    db_session, test_settings, tmp_path: Path
) -> None:
    path = tmp_path / "mix.xlsx"
    write_xlsx(
        path,
        HEADERS,
        [
            ["OK-1", "Норм", 10, 1, "", ""],
            ["BAD", "Плохо", "бесплатно", 1, "", ""],
        ],
    )
    report = await apply_price_import(
        db_session,
        content=path.read_bytes(),
        filename="mix.xlsx",
        admin_id=1001,
        admin_ids=test_settings.admin_ids,
        imports_dir=test_settings.imports_dir,
    )
    assert report.status == "applied"
    assert report.rows_ok == 1
    assert report.rows_err == 1
    assert await _count_sku(db_session, "OK-1") == 1
    assert await _count_sku(db_session, "BAD") == 0
