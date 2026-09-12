from pathlib import Path

from openpyxl import Workbook

HEADERS = (
    "артикул",
    "название",
    "категория",
    "описание",
    "цена",
    "остаток",
    "ед",
    "активен",
    "сортировка",
)

CATEGORIES: tuple[tuple[str, str, str], ...] = (
    ("Сухие смеси", "мешок", "Цемент"),
    ("Сыпучие", "кг", "Песок"),
    ("Кирпич", "шт", "Кирпич"),
    ("Арматура", "м", "Арматура"),
    ("Пиломатериалы", "м³", "Доска"),
    ("Крепёж", "упак", "Саморез"),
    ("Кровля", "лист", "Профнастил"),
    ("Утеплитель", "упак", "Минвата"),
    ("Электрика", "шт", "Кабель-канал"),
    ("Сантехника", "шт", "Труба ПП"),
)


def rows(count: int = 1000) -> list[tuple[object, ...]]:
    out: list[tuple[object, ...]] = []
    for index in range(1, count + 1):
        category, unit, stem = CATEGORIES[(index - 1) % len(CATEGORIES)]
        sku = f"PB-{index:04d}"
        variant = ((index - 1) // len(CATEGORIES)) + 1
        name = f"{stem} {variant:03d}"
        price = round(50 + (index % 97) * 12.5, 2)
        stock = (index * 3) % 200
        out.append(
            (
                sku,
                name,
                category,
                f"{name}, категория {category.lower()}",
                price,
                stock,
                unit,
                "да",
                index,
            )
        )
    return out


def write_catalog(path: Path, count: int = 1000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    book = Workbook()
    sheet = book.active
    sheet.append(list(HEADERS))
    for row in rows(count):
        sheet.append(list(row))
    book.save(path)
    return path


def main() -> None:
    target = Path(__file__).resolve().parents[1] / "content" / "sample_catalog_1000.xlsx"
    write_catalog(target)
    print(target)


if __name__ == "__main__":
    main()
