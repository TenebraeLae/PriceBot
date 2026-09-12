from pathlib import Path

from pricebot.domain.catalog import CatalogProduct, SearchPage, availability_label
from pricebot.services.import_catalog import ImportReport

BTN_CATALOG = "🛒 Каталог"
BTN_SEARCH = "🔎 Поиск"
BTN_ORDERS = "📦 Мои заказы"
BTN_INFO = "ℹ️ Информация"
BTN_SUPPORT = "📞 Поддержка"

MENU_BUTTONS = frozenset(
    {BTN_CATALOG, BTN_SEARCH, BTN_ORDERS, BTN_INFO, BTN_SUPPORT}
)

GREETING = "Добро пожаловать. Выберите пункт меню или введите название товара."
PROMPT_SEARCH = "Введите запрос: название, артикул или категория"
FORBIDDEN = "Недостаточно прав."
ORDERS_EMPTY = "Заказов пока нет."
QR_CAPTION = "Заказ {number}. К оплате {total} ₽."
SUPPORT_PROMPT = "Напишите сообщение — ответим в этом чате."
SUPPORT_ACCEPTED = "Обращение {ticket} принято. Ответим в этом чате."
SUPPORT_REPLY_HINT = "Формат: /reply T-YYYYMMDD-XXXX текст"
SUPPORT_REPLY_OK = "Ответ по {ticket} отправлен."
NOT_FOUND = "Ничего не найдено."
INFO_FALLBACK = "Прайс и заказы в Telegram."
DESC_LIMIT = 200


def default_info_path() -> Path:
    return Path(__file__).resolve().parents[2] / "content" / "info.txt"


def load_info_text(path: Path | None = None) -> str:
    info_path = path or default_info_path()
    try:
        text = info_path.read_text(encoding="utf-8").strip()
    except OSError:
        return INFO_FALLBACK
    return text or INFO_FALLBACK


def format_product_lines(product: CatalogProduct) -> str:
    description = (product.description or "").strip()
    if len(description) > DESC_LIMIT:
        description = description[:DESC_LIMIT].rstrip() + "…"
    lines = [
        product.name,
        product.sku,
        f"{product.price:.2f} ₽",
        availability_label(product.stock),
    ]
    if description:
        lines.append(description)
    return "\n".join(lines)


def format_search_message(page: SearchPage) -> str:
    if page.reason == "empty_query":
        hint = page.hint or PROMPT_SEARCH
        if page.category_hints:
            names = ", ".join(page.category_hints)
            return f"{hint}\nКатегории: {names}"
        return hint
    if page.reason == "user_blocked":
        return page.hint or "Поиск недоступен"
    if page.reason == "query_too_long":
        return "Запрос слишком длинный."
    if not page.items:
        return NOT_FOUND
    blocks = [format_product_lines(item) for item in page.items]
    return "\n\n".join(blocks)


def format_orders_message(orders) -> str:
    from pricebot.services.orders import format_orders_list

    return format_orders_list(orders)


def format_import_report(report: ImportReport) -> str:
    if report.status == "applied":
        text = f"Импорт применён: ок {report.rows_ok}, ошибок {report.rows_err}."
    else:
        reason = report.reject_reason or "файл отклонён"
        text = f"Импорт отклонён ({reason}). Каталог не изменён."
        if report.rows_err:
            text += f" Ошибок строк: {report.rows_err}."
    for err in report.errors:
        text += f"\nстр. {err.row}: {err.message}"
    return text
