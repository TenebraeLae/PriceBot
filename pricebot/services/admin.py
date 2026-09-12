from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pricebot.db.models import (
    Category,
    Order,
    OrderItem,
    PromoCode,
    SupportTicket,
    User,
)
from pricebot.domain.catalog import CatalogProduct
from pricebot.domain.errors import DomainError
from pricebot.domain.excel import export_catalog_xlsx
from pricebot.domain.photo import validate_product_photo
from pricebot.domain.payments import order_status_label
from pricebot.domain.promo import PromoKind, MOSCOW
from pricebot.domain.status import apply_admin_status
from pricebot.services.cache import invalidate_search_cache
from pricebot.services.notify import notify_order_status, notify_ticket_reply
from pricebot.services.search import to_catalog_product
from pricebot.config import Settings
from pricebot.db.models import Product


def _iso(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=MOSCOW)
    return moment.isoformat()


def _order_admin_payload(order: Order) -> dict[str, object]:
    return {
        "number": order.number,
        "telegram_id": order.user_id,
        "total": str(order.total),
        "status": order.status,
        "status_label": order_status_label(order.status),
        "promo_code": order.promo_code,
        "created_at": _iso(order.created_at),
        "paid_at": _iso(order.paid_at),
        "items": [
            {
                "sku": item.sku,
                "name": item.name,
                "qty": str(item.qty),
                "price_snapshot": str(item.price_snapshot),
            }
            for item in order.items
        ],
    }


async def search_admin_orders(
    session: AsyncSession,
    *,
    number: str | None = None,
    telegram_id: int | None = None,
    sku: str | None = None,
    status: str | None = None,
) -> list[Order]:
    stmt = select(Order)
    if number:
        stmt = stmt.where(Order.number.ilike(f"%{number.strip()}%"))
    if telegram_id is not None:
        stmt = stmt.where(Order.user_id == telegram_id)
    if status:
        stmt = stmt.where(Order.status == status)
    if sku:
        stmt = stmt.join(OrderItem).where(OrderItem.sku.ilike(f"%{sku.strip()}%")).distinct()
    stmt = stmt.order_by(Order.created_at.desc(), Order.id.desc())
    result = await session.execute(stmt)
    orders = list(result.scalars().unique().all())
    for order in orders:
        await session.refresh(order, attribute_names=["items"])
    return orders


async def set_admin_order_status(
    session: AsyncSession,
    *,
    number: str,
    status: str,
    settings: Settings,
) -> Order:
    result = await session.execute(select(Order).where(Order.number == number))
    order = result.scalar_one_or_none()
    if order is None:
        raise DomainError("order_not_found", "Заказ не найден")
    next_status = apply_admin_status(order.status, status)
    order.status = next_status.value
    await session.commit()
    await notify_order_status(settings, order.user_id, order.number, order.status)
    await session.refresh(order, attribute_names=["items"])
    return order


async def list_admin_users(session: AsyncSession) -> list[User]:
    result = await session.execute(select(User).order_by(User.telegram_id.asc()))
    return list(result.scalars().all())


async def set_user_blocked(session: AsyncSession, telegram_id: int, *, blocked: bool) -> User:
    user = await session.get(User, telegram_id)
    if user is None:
        raise DomainError("user_not_found", "Пользователь не найден")
    user.status = "blocked" if blocked else "active"
    await session.commit()
    return user


def _parse_dt(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        moment = value
    else:
        moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        return moment.replace(tzinfo=MOSCOW)
    return moment.astimezone(MOSCOW)


async def create_promo(
    session: AsyncSession,
    *,
    code: str,
    kind: str,
    value: Decimal | str | int,
    starts_at: datetime | str,
    ends_at: datetime | str,
    max_uses: int | None = None,
    active: bool = True,
) -> PromoCode:
    normalized = code.strip().upper()
    if not normalized:
        raise DomainError("promo_invalid", "Промокод неверен")
    try:
        promo_kind = PromoKind(kind)
    except ValueError as exc:
        raise DomainError("promo_invalid", "Промокод неверен") from exc
    existing = await session.execute(select(PromoCode).where(PromoCode.code == normalized))
    if existing.scalar_one_or_none() is not None:
        raise DomainError("promo_exists", "Промокод уже существует")
    promo = PromoCode(
        code=normalized,
        kind=promo_kind.value,
        value=Decimal(str(value)),
        starts_at=_parse_dt(starts_at),
        ends_at=_parse_dt(ends_at),
        max_uses=max_uses,
        used_count=0,
        active=active,
    )
    session.add(promo)
    await session.commit()
    await session.refresh(promo)
    return promo


async def disable_promo(session: AsyncSession, code: str) -> PromoCode:
    result = await session.execute(select(PromoCode).where(PromoCode.code == code.strip().upper()))
    promo = result.scalar_one_or_none()
    if promo is None:
        raise DomainError("promo_invalid", "Промокод неверен")
    promo.active = False
    await session.commit()
    return promo


def promo_json(promo: PromoCode) -> dict[str, object]:
    return {
        "code": promo.code,
        "kind": promo.kind,
        "value": str(promo.value),
        "starts_at": _iso(promo.starts_at),
        "ends_at": _iso(promo.ends_at),
        "max_uses": promo.max_uses,
        "used_count": promo.used_count,
        "active": promo.active,
    }


def user_json(user: User) -> dict[str, object]:
    return {
        "telegram_id": user.telegram_id,
        "username": user.username,
        "status": user.status,
        "first_seen_at": _iso(user.first_seen_at),
    }


async def list_admin_tickets(session: AsyncSession, *, status: str = "open") -> list[SupportTicket]:
    stmt = select(SupportTicket).order_by(SupportTicket.id.desc())
    if status != "all":
        stmt = stmt.where(SupportTicket.status == status)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def reply_ticket(
    session: AsyncSession,
    *,
    ticket: str,
    text: str,
    settings: Settings,
) -> SupportTicket:
    message = (text or "").strip()
    if not message:
        raise DomainError("ticket_empty", "Пустой ответ")
    result = await session.execute(select(SupportTicket).where(SupportTicket.ticket == ticket))
    row = result.scalar_one_or_none()
    if row is None:
        raise DomainError("ticket_not_found", "Обращение не найдено")
    row.admin_reply = message
    row.status = "closed"
    await session.commit()
    await notify_ticket_reply(settings, row.user_id, row.ticket, message)
    return row


def ticket_json(row: SupportTicket) -> dict[str, object]:
    return {
        "ticket": row.ticket,
        "telegram_id": row.user_id,
        "message": row.message,
        "admin_reply": row.admin_reply,
        "status": row.status,
    }


async def attach_product_photo(
    session: AsyncSession,
    *,
    sku: str,
    content: bytes,
    media_dir: str,
    redis_url: str | None = None,
) -> Product:
    result = await session.execute(select(Product).where(Product.sku == sku))
    row = result.scalar_one_or_none()
    if row is None:
        raise DomainError("sku_not_found", f"Товар с артикулом {sku} не найден.")
    validate_product_photo(content)
    root = Path(media_dir)
    root.mkdir(parents=True, exist_ok=True)
    filename = f"{sku}.jpg"
    (root / filename).write_bytes(content)
    row.photo_url = filename
    await session.commit()
    await invalidate_search_cache(redis_url)
    return row


async def export_catalog_bytes(session: AsyncSession) -> bytes:
    rows = await session.execute(
        select(Product, func.coalesce(Category.name, ""))
        .outerjoin(Category, Product.category_id == Category.id)
        .order_by(Product.sort.asc(), Product.sku.asc())
    )
    products: list[CatalogProduct] = [
        to_catalog_product(product, category) for product, category in rows.all()
    ]
    return export_catalog_xlsx(products)
