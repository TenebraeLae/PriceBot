from pathlib import Path

from pricebot.bot.handlers import AdminReplyPendingStore
from pricebot.bot.keyboards import (
    CALLBACK_ADMIN_REPLY,
    CALLBACK_PAGE_PREFIX,
    main_keyboard,
    search_inline_keyboard,
    ticket_reply_keyboard,
)
from pricebot.bot.main import build_dispatcher
from pricebot.bot.texts import (
    BTN_ADMIN,
    BTN_CATALOG,
    BTN_INFO,
    BTN_ORDERS,
    BTN_SEARCH,
    BTN_SUPPORT,
    FORBIDDEN,
    GREETING,
    ORDERS_EMPTY,
    PROMPT_SEARCH,
    SUPPORT_PROMPT,
    SUPPORT_REPLY_HINT,
    format_import_report,
    format_product_lines,
    format_search_message,
    load_info_text,
)
from pricebot.domain.catalog import CatalogProduct, SearchPage
from pricebot.services.import_catalog import ImportReport
from pricebot.services.search import LastQueryStore
from tests.conftest import make_test_settings


def test_main_keyboard_menu_without_catalog() -> None:
    markup = main_keyboard("https://example.invalid/app")
    labels = [button.text for row in markup.keyboard for button in row]
    assert labels == [BTN_SEARCH, BTN_ORDERS, BTN_INFO, BTN_SUPPORT]
    assert BTN_CATALOG not in labels
    assert all(button.web_app is None for row in markup.keyboard for button in row)


def test_main_keyboard_admin_includes_admin_button() -> None:
    markup = main_keyboard("https://example.invalid/app", admin=True)
    labels = [button.text for row in markup.keyboard for button in row]
    assert BTN_ADMIN in labels
    assert BTN_CATALOG not in labels
    assert markup.keyboard[2][0].text == BTN_ADMIN


def test_ticket_reply_keyboard_callback_data() -> None:
    markup = ticket_reply_keyboard("T-20260912-0001")
    button = markup.inline_keyboard[0][0]
    assert button.text == "Ответить"
    assert button.callback_data == f"{CALLBACK_ADMIN_REPLY}T-20260912-0001"


def test_admin_reply_pending_store_mark_take() -> None:
    store = AdminReplyPendingStore()
    store.mark(1001, "T-20260912-0001")
    assert store.take(1001) == "T-20260912-0001"
    assert store.take(1001) is None


def test_info_orders_support_and_greeting_texts() -> None:
    info = load_info_text()
    assert "Прайс" in info
    assert ORDERS_EMPTY == "Заказов пока нет."
    assert SUPPORT_PROMPT.startswith("Напишите")
    assert "Ответить" in SUPPORT_REPLY_HINT or "Админк" in SUPPORT_REPLY_HINT
    assert GREETING
    assert "Введите запрос" in PROMPT_SEARCH
    assert FORBIDDEN == "Недостаточно прав."


def test_search_message_russian_fields(cement: CatalogProduct) -> None:
    text = format_product_lines(cement)
    assert "Цемент М500" in text
    assert "CEM-M500" in text
    assert "450.00 ₽" in text
    assert "в наличии" in text
    assert "Мешок 50 кг" in text
    empty = format_search_message(
        SearchPage(items=[], page=1, page_size=10, total=0, reason="ok")
    )
    assert empty == "Ничего не найдено."


def test_pagination_inline_and_last_query() -> None:
    items = [
        CatalogProduct(sku=f"S{i}", name="бетон", price=cement_price(), stock=1, sort=i)
        for i in range(11)
    ]
    page = SearchPage(items=items[:10], page=1, page_size=10, total=11, reason="ok")
    markup = search_inline_keyboard(page, "https://example.invalid/app")
    assert markup is not None
    data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
    texts = [btn.text for row in markup.inline_keyboard for btn in row]
    assert f"{CALLBACK_PAGE_PREFIX}2" in data
    assert "В Mini App" not in texts
    store = LastQueryStore()
    store.put(7, "бетон")
    assert store.get(7) == "бетон"


def cement_price():
    from decimal import Decimal

    return Decimal("1")


def test_import_report_rejected_mentions_catalog() -> None:
    text = format_import_report(
        ImportReport(
            status="rejected",
            rows_ok=0,
            rows_err=1,
            reject_reason="missing_headers",
            import_id=1,
            saved_path="x.xlsx",
        )
    )
    assert "отклонён" in text
    assert "не изменён" in text


def test_dispatcher_wires_workflow(tmp_path: Path) -> None:
    settings = make_test_settings(tmp_path)
    dispatcher = build_dispatcher(settings, object())  # type: ignore[arg-type]
    assert dispatcher.sub_routers
    assert dispatcher["settings"] is settings
    assert isinstance(dispatcher["query_store"], LastQueryStore)
    assert isinstance(dispatcher["admin_reply_store"], AdminReplyPendingStore)
