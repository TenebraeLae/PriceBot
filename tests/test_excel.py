from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook

from pricebot.domain.excel import parse_excel


def write_xlsx(path: Path, headers: list[str], rows: list[list[object]]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    workbook.save(path)

HEADERS_RU = ["артикул", "название", "категория", "цена", "остаток", "ед", "фото"]
HEADERS_EN = ["sku", "name", "price", "stock"]


def test_parse_ru_aliases(tmp_path: Path) -> None:
    path = tmp_path / "ok.xlsx"
    write_xlsx(path, HEADERS_RU, [["CEM-M500", "Цемент М500", "Смеси", "450,50", 10, "мешок", ""]])
    result = parse_excel(path)
    assert result.import_status == "applied"
    assert len(result.rows_ok) == 1
    row = result.rows_ok[0]
    assert row.sku == "CEM-M500"
    assert row.price == Decimal("450.50")
    assert row.unit == "мешок"


def test_empty_file_rejected() -> None:
    result = parse_excel(b"")
    assert result.accepted is False
    assert result.import_status == "rejected"


def test_missing_headers_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.xlsx"
    write_xlsx(path, ["foo", "bar"], [["a", "b"]])
    result = parse_excel(path)
    assert result.accepted is False
    assert result.reject_reason == "missing_headers"


def test_price_free_is_row_error(tmp_path: Path) -> None:
    path = tmp_path / "free.xlsx"
    write_xlsx(path, HEADERS_EN, [["A", "Товар", "бесплатно", 1]])
    result = parse_excel(path)
    assert result.rows_ok == []
    assert result.import_status == "rejected"
    assert result.rows_err[0].message


def test_negative_stock_is_row_error(tmp_path: Path) -> None:
    path = tmp_path / "neg.xlsx"
    write_xlsx(path, HEADERS_EN, [["A", "Товар", 10, -1]])
    result = parse_excel(path)
    assert result.rows_ok == []
    assert "остаток" in result.rows_err[0].message.casefold()


def test_duplicate_sku_first_valid_wins(tmp_path: Path) -> None:
    path = tmp_path / "dup.xlsx"
    write_xlsx(
        path,
        HEADERS_EN,
        [
            ["A", "Первый", 10, 1],
            ["A", "Второй", 20, 1],
        ],
    )
    result = parse_excel(path)
    assert len(result.rows_ok) == 1
    assert result.rows_ok[0].name == "Первый"
    assert result.rows_err[0].message == "Дубль sku"


def test_zero_valid_rejected_partial_applied(tmp_path: Path) -> None:
    empty_ok = tmp_path / "zero.xlsx"
    write_xlsx(empty_ok, HEADERS_EN, [["A", "Товар", "бесплатно", 1]])
    zero = parse_excel(empty_ok)
    assert zero.import_status == "rejected"
    assert zero.accepted is False
    assert zero.reject_reason == "no_valid_rows"

    mixed = tmp_path / "mix.xlsx"
    write_xlsx(
        mixed,
        HEADERS_EN,
        [
            ["A", "Ок", 10, 1],
            ["B", "Плохо", "бесплатно", 1],
        ],
    )
    parsed = parse_excel(mixed)
    assert parsed.import_status == "applied"
    assert [row.sku for row in parsed.rows_ok] == ["A"]
    assert len(parsed.rows_err) == 1


def test_too_many_rows_rejected(tmp_path: Path) -> None:
    path = tmp_path / "huge.xlsx"
    write_xlsx(path, HEADERS_EN, [["A", "1", 1, 1], ["B", "2", 1, 1], ["C", "3", 1, 1]])
    result = parse_excel(path, max_rows=2)
    assert result.accepted is False
    assert result.reject_reason == "too_many_rows"


def test_extra_columns_ignored(tmp_path: Path) -> None:
    path = tmp_path / "extra.xlsx"
    write_xlsx(path, ["sku", "name", "price", "comment"], [["X", "Товар", 5, "ignore-me"]])
    result = parse_excel(path)
    assert result.rows_ok[0].sku == "X"
    assert result.rows_ok[0].price == Decimal("5")


def test_zero_or_empty_price_is_row_error(tmp_path: Path) -> None:
    zero_path = tmp_path / "zero-price.xlsx"
    write_xlsx(zero_path, HEADERS_EN, [["A", "Товар", 0, 1]])
    zero = parse_excel(zero_path)
    assert zero.accepted is False
    assert zero.rows_ok == []
    assert "цена" in zero.rows_err[0].message.casefold()

    empty_path = tmp_path / "empty-price.xlsx"
    write_xlsx(empty_path, HEADERS_EN, [["B", "Товар", "", 1]])
    empty = parse_excel(empty_path)
    assert empty.accepted is False
    assert empty.rows_ok == []
