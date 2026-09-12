import logging
from io import BytesIO
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import BufferedInputFile, CallbackQuery, FSInputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pricebot.bot.keyboards import (
    CALLBACK_ADMIN_LIST,
    CALLBACK_ADMIN_REPLY,
    CALLBACK_PAGE_PREFIX,
    admin_home_keyboard,
    main_keyboard,
    search_inline_keyboard,
    ticket_reply_keyboard,
)
from pricebot.bot.texts import (
    ADMIN_HOME,
    ADMIN_REPLY_PROMPT,
    ADMIN_TICKETS_EMPTY,
    BTN_ADMIN,
    BTN_INFO,
    BTN_ORDERS,
    BTN_SEARCH,
    BTN_SUPPORT,
    FORBIDDEN,
    GREETING,
    IMPORT_ALREADY,
    IMPORT_FAILED,
    IMPORT_STARTED,
    MENU_BUTTONS,
    PHOTO_BAD_SKU,
    PHOTO_NEED_CAPTION,
    PHOTO_SAVED,
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
from pricebot.domain.photo import is_http_photo, local_media_path, resolve_product_photo, safe_sku
from pricebot.domain.qr import render_qr
from pricebot.services.import_catalog import apply_price_import
from pricebot.services.orders import (
    first_payment,
    format_orders_list,
    list_user_orders,
    payment_payload_url,
)
from pricebot.services.admin import attach_product_photo, list_admin_tickets, reply_ticket
from pricebot.services.search import LastQueryStore, search_products_db
from pricebot.services.tickets import create_ticket
from pricebot.services.users import upsert_user
from pricebot.web.update_dedup import SEEN_IMPORTS


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


class AdminReplyPendingStore:
    def __init__(self) -> None:
        self._pending: dict[int, str] = {}

    def mark(self, user_id: int, ticket: str) -> None:
        self._pending[user_id] = ticket

    def take(self, user_id: int) -> str | None:
        return self._pending.pop(user_id, None)


def _is_admin(user, settings: Settings) -> bool:
    return user is not None and user.id in settings.admin_ids


def _menu_markup(settings: Settings, user):
    return main_keyboard(settings.webapp_url, admin=_is_admin(user, settings))


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
        await message.answer(GREETING, reply_markup=_menu_markup(settings, user))

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

    @router.message(F.text == BTN_ADMIN)
    async def menu_admin(message: Message, settings: Settings) -> None:
        if not _is_admin(message.from_user, settings):
            await message.answer(FORBIDDEN)
            return
        await message.answer(ADMIN_HOME, reply_markup=admin_home_keyboard())

    @router.callback_query(F.data == CALLBACK_ADMIN_LIST)
    async def admin_list_tickets(
        callback: CallbackQuery,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        if not _is_admin(callback.from_user, settings):
            await callback.answer(FORBIDDEN, show_alert=True)
            return
        async with session_factory() as session:
            rows = await list_admin_tickets(session, status="open")
        target = callback.message
        if not rows:
            if target is not None:
                await target.answer(ADMIN_TICKETS_EMPTY)
            await callback.answer()
            return
        if target is None:
            await callback.answer()
            return
        for row in rows:
            body = f"Обращение {row.ticket} от {row.user_id}:\n{row.message}"
            await target.answer(body, reply_markup=ticket_reply_keyboard(row.ticket))
        await callback.answer()

    @router.callback_query(F.data.startswith(CALLBACK_ADMIN_REPLY))
    async def admin_reply_begin(
        callback: CallbackQuery,
        settings: Settings,
        admin_reply_store: AdminReplyPendingStore,
    ) -> None:
        if not _is_admin(callback.from_user, settings):
            await callback.answer(FORBIDDEN, show_alert=True)
            return
        ticket = (callback.data or "")[len(CALLBACK_ADMIN_REPLY) :]
        if not ticket:
            await callback.answer()
            return
        user = callback.from_user
        if user is not None:
            admin_reply_store.mark(user.id, ticket)
        target = callback.message
        if target is not None:
            await target.answer(ADMIN_REPLY_PROMPT)
        await callback.answer()

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
            await message.answer("Пришлите файл .xlsx")
            return
        filename = document.file_name or "price.xlsx"
        if not filename.lower().endswith(".xlsx"):
            await message.answer("Пришлите файл .xlsx")
            return
        file_key = document.file_unique_id or document.file_id
        if not SEEN_IMPORTS.add_new(file_key):
            await message.answer(IMPORT_ALREADY)
            return
        await message.answer(IMPORT_STARTED)
        buffer = BytesIO()
        try:
            await bot.download(document, destination=buffer)
            async with session_factory() as session:
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
            SEEN_IMPORTS.discard(file_key)
            await message.answer(exc.message)
            return
        except Exception:
            SEEN_IMPORTS.discard(file_key)
            logging.getLogger(__name__).exception("xlsx import failed")
            await message.answer(IMPORT_FAILED)
            return
        await message.answer(format_import_report(report))

    @router.message(F.photo)
    async def admin_product_photo(
        message: Message,
        bot: Bot,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        if not _is_admin(message.from_user, settings):
            await message.answer(FORBIDDEN)
            return
        caption = (message.caption or '').strip()
        if not caption:
            await message.answer(PHOTO_NEED_CAPTION)
            return
        sku = safe_sku(caption.split()[0])
        if sku is None:
            await message.answer(PHOTO_BAD_SKU)
            return
        photos = message.photo or []
        if not photos:
            await message.answer(PHOTO_NEED_CAPTION)
            return
        buffer = BytesIO()
        try:
            await bot.download(photos[-1], destination=buffer)
            async with session_factory() as session:
                await attach_product_photo(
                    session,
                    sku=sku,
                    content=buffer.getvalue(),
                    media_dir=settings.media_dir,
                    redis_url=settings.redis_url,
                )
        except DomainError as exc:
            await message.answer(exc.message)
            return
        await message.answer(PHOTO_SAVED.format(sku=sku))

    @router.message(F.text)
    async def text_search(
        message: Message,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        query_store: LastQueryStore,
        support_store: SupportPendingStore,
        admin_reply_store: AdminReplyPendingStore,
    ) -> None:
        text = (message.text or "").strip()
        if not text or text in MENU_BUTTONS:
            return
        user = message.from_user
        owner_id = user.id if user is not None else message.chat.id
        pending_ticket = admin_reply_store.take(owner_id)
        if pending_ticket:
            if not _is_admin(user, settings):
                await message.answer(FORBIDDEN)
                return
            async with session_factory() as session:
                try:
                    row = await reply_ticket(
                        session, ticket=pending_ticket, text=text, settings=settings
                    )
                except DomainError as exc:
                    await message.answer(exc.message)
                    return
            await message.answer(SUPPORT_REPLY_OK.format(ticket=row.ticket))
            return
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
