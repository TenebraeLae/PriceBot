from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from pricebot.bot.texts import (
    BTN_CATALOG,
    BTN_INFO,
    BTN_ORDERS,
    BTN_SEARCH,
    BTN_SUPPORT,
)
from pricebot.domain.catalog import SearchPage

CALLBACK_PAGE_PREFIX = "s:"


def main_keyboard(webapp_url: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_CATALOG, web_app=WebAppInfo(url=webapp_url))],
            [KeyboardButton(text=BTN_SEARCH), KeyboardButton(text=BTN_ORDERS)],
            [KeyboardButton(text=BTN_INFO), KeyboardButton(text=BTN_SUPPORT)],
        ],
        resize_keyboard=True,
    )


def search_inline_keyboard(page: SearchPage, webapp_url: str) -> InlineKeyboardMarkup | None:
    buttons: list[list[InlineKeyboardButton]] = []
    nav: list[InlineKeyboardButton] = []
    if page.page > 1:
        nav.append(
            InlineKeyboardButton(
                text="« Назад",
                callback_data=f"{CALLBACK_PAGE_PREFIX}{page.page - 1}",
            )
        )
    has_next = page.page * page.page_size < page.total
    if has_next:
        nav.append(
            InlineKeyboardButton(
                text="Далее »",
                callback_data=f"{CALLBACK_PAGE_PREFIX}{page.page + 1}",
            )
        )
    if nav:
        buttons.append(nav)
    if page.items:
        buttons.append(
            [InlineKeyboardButton(text="В Mini App", web_app=WebAppInfo(url=webapp_url))]
        )
    if not buttons:
        return None
    return InlineKeyboardMarkup(inline_keyboard=buttons)
