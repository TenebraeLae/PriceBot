from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

from pricebot.bot.texts import (
    BTN_ADMIN,
    BTN_CATALOG,
    BTN_INFO,
    BTN_ORDERS,
    BTN_SEARCH,
    BTN_SUPPORT,
)
from pricebot.domain.catalog import SearchPage

CALLBACK_PAGE_PREFIX = "s:"
CALLBACK_ADMIN_REPLY = "a:r:"
CALLBACK_ADMIN_LIST = "a:list"


def is_https_webapp_url(url: str) -> bool:
    return url.startswith("https://")


def catalog_button(webapp_url: str) -> KeyboardButton:
    if is_https_webapp_url(webapp_url):
        return KeyboardButton(text=BTN_CATALOG, web_app=WebAppInfo(url=webapp_url))
    return KeyboardButton(text=BTN_CATALOG)


def main_keyboard(webapp_url: str, *, admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [catalog_button(webapp_url)],
        [KeyboardButton(text=BTN_SEARCH), KeyboardButton(text=BTN_ORDERS)],
        [KeyboardButton(text=BTN_INFO), KeyboardButton(text=BTN_SUPPORT)],
    ]
    if admin:
        rows.append([KeyboardButton(text=BTN_ADMIN)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def ticket_reply_keyboard(ticket: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Ответить",
                    callback_data=f"{CALLBACK_ADMIN_REPLY}{ticket}",
                )
            ]
        ]
    )


def admin_home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Открытые обращения",
                    callback_data=CALLBACK_ADMIN_LIST,
                )
            ]
        ]
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
    if page.items and is_https_webapp_url(webapp_url):
        buttons.append(
            [InlineKeyboardButton(text="В Mini App", web_app=WebAppInfo(url=webapp_url))]
        )
    if not buttons:
        return None
    return InlineKeyboardMarkup(inline_keyboard=buttons)
