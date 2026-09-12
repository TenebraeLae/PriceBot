from io import BytesIO
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import BufferedInputFile, CallbackQuery, FSInputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pricebot.bot.keyboards import (
    CALLBACK_PAGE_PREFIX,
    main_keyboard,
    search_inline_keyboard,
)
from pricebot.bot.texts import (
    BTN_INFO,
    BTN_ORDERS,
    BTN_SEARCH,
    BTN_SUPPORT,
    FORBIDDEN,
    GREETING,
    MENU_BUTTONS,
    PROMPT_SEARCH,
    QR_CAPTION,
    SUPPORT_ACCEPTED,
    SUPPORT_PROMPT,
    SUPPORT_REPLY_HINT,
    SUPPORT_REPLY_OK,
    format_import_report,
    format_search_message,
    load_info_text,
)
from pricebot.config import Settings
from pricebot.domain.errors import DomainError
from pricebot.domain.payments import OrderStatus
from pricebot.domain.photo import is_http_photo, local_media_path, resolve_product_photo
from pricebot.domain.qr import render_qr
from pricebot.services.import_catalog import apply_price_import
from pricebot.services.orders import (
    first_payment,
    format_orders_list,
    list_user_orders,
    payment_payload_url,
)
from pricebot.services.admin import reply_ticket
from pricebot.services.search import LastQueryStore, search_products_db
from pricebot.services.tickets import create_ticket
from pricebot.services.users import upsert_user


class SupportPendingStore:
    def __init__(self) -> None:
        self._pending: set[int] = set()

    def mark(self, user_id: int) -> None:
        self._pending.add(user_id)

    def take(self, user_id: int) -> bool:
        if user_id in self._pending:
            self._pending.discard(user_id)
            return True
        return False


def build_router() -> Router:
    router = Router()

    @router.message(CommandStart())
    async def cmd_start(
        message: Message,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        user = message.from_user
        if user is not None:
            async with session_factory() as session:
                await upsert_user(session, user.id, user.username)
                await session.commit()
        await message.answer(GREETING, reply_markup=main_keyboard(settings.webapp_url))

    @router.message(F.text == BTN_SEARCH)
    async def menu_search(message: Message) -> None:
        await message.answer(PROMPT_SEARCH)

    @router.message(F.text == BTN_ORDERS)
    async def menu_orders(
        message: Message,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        user = message.from_user
        if user is None:
            await message.answer(format_orders_list([]))
            return
        async with session_factory() as session:
            await upsert_user(session, user.id, user.username)
            orders = await list_user_orders(session, user.id)
            for order in orders:
                await session.refresh(order, attribute_names=["payments"])
        await message.answer(format_orders_list(orders))
        for order in orders:
            if order.status != OrderStatus.awaiting_payment.value:
                continue
            payment = first_payment(order)
            if payment is None:
                continue
            png = render_qr(payment_payload_url(payment)).png_bytes
            caption = QR_CAPTION.format(number=order.number, total=order.total)
            await message.answer_photo(
                BufferedInputFile(png, filename="qr.png"),
                caption=caption,
            )

    @router.message(F.text == BTN_INFO)
    async def menu_info(message: Message, info_path: Path) -> None:
        await message.answer(load_info_text(info_path))

    @router.message(F.text == BTN_SUPPORT)
    async def menu_support(message: Message, support_store: SupportPendingStore) -> None:
        user = message.from_user
        if user is not None:
            support_store.mark(user.id)
        await message.answer(SUPPORT_PROMPT)

    @router.message(Command("reply"))
    async def admin_reply_ticket(
        message: Message,
        command: CommandObject,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        user = message.from_user
        if user is None or user.id not in settings.admin_ids:
            await message.answer(FORBIDDEN)
            return
        raw = (command.args or "").strip()
        parts = raw.split(maxsplit=1)
        if len(parts) < 2:
            await message.answer(SUPPORT_REPLY_HINT)
            return
        ticket_id, reply_text = parts
        async with session_factory() as session:
            try:
                row = await reply_ticket(
                    session, ticket=ticket_id, text=reply_text, settings=settings
                )
            except DomainError as exc:
                await message.answer(exc.message)
                return
        await message.answer(SUPPORT_REPLY_OK.format(ticket=row.ticket))

    @router.message(F.document)
    async def admin_xlsx(
        message: Message,
        bot: Bot,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        user = message.from_user
        if user is None or user.id not in settings.admin_ids:
            await message.answer(FORBIDDEN)
            return
        document = message.document
        if document is None:
            return
        filename = document.file_name or "price.xlsx"
        if not filename.lower().endswith(".xlsx"):
            await message.answer("Пришлите файл .xlsx")
            return
        buffer = BytesIO()
        await bot.download(document, destination=buffer)
        async with session_factory() as session:
            try:
                report = await apply_price_import(
                    session,
                    content=buffer.getvalue(),
                    filename=filename,
                    admin_id=user.id,
                    admin_ids=settings.admin_ids,
                    imports_dir=settings.imports_dir,
                    max_rows=settings.max_import_rows,
                    timezone_name=settings.timezone,
                    redis_url=settings.redis_url,
                )
            except DomainError as exc:
                await message.answer(exc.message)
                return
        await message.answer(format_import_report(report))

    @router.message(F.text)
    async def text_search(
        message: Message,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        query_store: LastQueryStore,
        support_store: SupportPendingStore,
    ) -> None:
        text = (message.text or "").strip()
        if not text or text in MENU_BUTTONS:
            return
        user = message.from_user
        owner_id = user.id if user is not None else message.chat.id
        if support_store.take(owner_id):
            async with session_factory() as session:
                await upsert_user(session, owner_id, user.username if user else None)
                ticket = await create_ticket(
                    session, user_id=owner_id, message=text, settings=settings
                )
            await message.answer(SUPPORT_ACCEPTED.format(ticket=ticket.ticket))
            return
        await _reply_search(
            message,
            session_factory,
            settings,
            query_store,
            text,
            owner_id=owner_id,
            page=1,
        )

    @router.callback_query(F.data.startswith(CALLBACK_PAGE_PREFIX))
    async def search_page(
        callback: CallbackQuery,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        query_store: LastQueryStore,
    ) -> None:
        user = callback.from_user
        raw = (callback.data or "")[len(CALLBACK_PAGE_PREFIX) :]
        try:
            page = int(raw)
        except ValueError:
            await callback.answer()
            return
        if user is None:
            await callback.answer()
            return
        query = query_store.get(user.id)
        if not query:
            await callback.answer(PROMPT_SEARCH)
            return
        if callback.message is None:
            await callback.answer()
            return
        await _reply_search(
            callback.message,
            session_factory,
            settings,
            query_store,
            query,
            owner_id=user.id,
            page=page,
            edit=True,
        )
        await callback.answer()

    return router


def _card_photo_input(items, media_dir: str):
    if len(items) != 1:
        return None
    raw = resolve_product_photo(items[0].photo_url)
    if raw is None:
        return None
    if is_http_photo(raw):
        return raw
    path = local_media_path(raw, media_dir)
    if path is None:
        return None
    return FSInputFile(path)


async def _reply_search(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    query_store: LastQueryStore,
    query: str,
    *,
    owner_id: int,
    page: int,
    edit: bool = False,
) -> None:
    async with session_factory() as session:
        db_user = await upsert_user(session, owner_id)
        result = await search_products_db(
            session,
            query,
            page=page,
            page_size=settings.page_size,
            user_status=db_user.status,
        )
        await session.commit()
    if result.reason == "ok" and query.strip():
        query_store.put(owner_id, query)
    text = format_search_message(result)
    markup = search_inline_keyboard(result, settings.webapp_url)
    if edit:
        await message.edit_text(text, reply_markup=markup)
        return
    card_photo = _card_photo_input(result.items, settings.media_dir)
    if card_photo is not None:
        await message.answer_photo(card_photo, caption=text, reply_markup=markup)
        return
    await message.answer(text, reply_markup=markup)
