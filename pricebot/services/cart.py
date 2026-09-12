from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pricebot.db.models import Cart, CartItem, Category, Product, User
from pricebot.domain.access import ensure_active_user
from pricebot.domain.cart import CartLine, as_qty, cart_subtotal, validate_cart_qty
from pricebot.domain.catalog import CatalogProduct
from pricebot.domain.errors import DomainError
from pricebot.services.search import to_catalog_product
from pricebot.services.users import upsert_user


def _http_qty(value: Decimal) -> str:
    return str(value)


async def _get_product_by_sku(session: AsyncSession, sku: str) -> tuple[Product, CatalogProduct]:
    row = await session.execute(
        select(Product, func.coalesce(Category.name, ""))
        .outerjoin(Category, Product.category_id == Category.id)
        .where(Product.sku == sku)
    )
    found = row.first()
    if found is None:
        raise DomainError("sku_not_found", "Товар не найден")
    product, category_name = found
    return product, to_catalog_product(product, category_name)


async def _get_or_create_cart(session: AsyncSession, telegram_id: int) -> Cart:
    result = await session.execute(select(Cart).where(Cart.user_id == telegram_id))
    cart = result.scalar_one_or_none()
    if cart is not None:
        return cart
    user = await session.get(User, telegram_id)
    if user is None:
        await upsert_user(session, telegram_id)
    cart = Cart(user_id=telegram_id)
    session.add(cart)
    await session.flush()
    return cart


async def load_cart_lines(session: AsyncSession, telegram_id: int) -> list[CartLine]:
    cart_row = await session.execute(select(Cart).where(Cart.user_id == telegram_id))
    cart = cart_row.scalar_one_or_none()
    if cart is None:
        return []
    rows = await session.execute(
        select(CartItem, Product, func.coalesce(Category.name, ""))
        .join(Product, CartItem.product_id == Product.id)
        .outerjoin(Category, Product.category_id == Category.id)
        .where(CartItem.cart_id == cart.id)
        .order_by(Product.sort.asc(), Product.sku.asc())
    )
    lines: list[CartLine] = []
    for item, product, category_name in rows.all():
        lines.append(CartLine(product=to_catalog_product(product, category_name), qty=item.qty))
    return lines


def cart_payload(lines: list[CartLine]) -> dict[str, object]:
    items = []
    for line in lines:
        items.append(
            {
                "sku": line.product.sku,
                "name": line.product.name,
                "qty": _http_qty(line.qty),
                "price": str(line.product.price),
                "line_total": str(line.line_total),
                "unit": line.product.unit,
                "stock": str(line.product.stock),
                "photo_url": line.product.photo_url,
            }
        )
    return {"items": items, "total": str(cart_subtotal(lines))}


async def get_cart(session: AsyncSession, telegram_id: int) -> dict[str, object]:
    lines = await load_cart_lines(session, telegram_id)
    return cart_payload(lines)


async def _save_line(
    session: AsyncSession,
    telegram_id: int,
    sku: str,
    qty: Decimal,
    *,
    user_status: str,
) -> dict[str, object]:
    ensure_active_user(user_status)
    product, catalog = await _get_product_by_sku(session, sku)
    amount = validate_cart_qty(catalog, qty)
    cart = await _get_or_create_cart(session, telegram_id)
    existing = await session.execute(
        select(CartItem).where(CartItem.cart_id == cart.id, CartItem.product_id == product.id)
    )
    item = existing.scalar_one_or_none()
    if item is None:
        session.add(CartItem(cart_id=cart.id, product_id=product.id, qty=amount))
    else:
        item.qty = amount
    await session.flush()
    return await get_cart(session, telegram_id)


async def add_cart_item(
    session: AsyncSession,
    telegram_id: int,
    sku: str,
    qty: Decimal | int | str,
    *,
    user_status: str,
) -> dict[str, object]:
    ensure_active_user(user_status)
    product, catalog = await _get_product_by_sku(session, sku)
    incoming = as_qty(qty)
    validate_cart_qty(catalog, incoming)
    cart = await _get_or_create_cart(session, telegram_id)
    existing = await session.execute(
        select(CartItem).where(CartItem.cart_id == cart.id, CartItem.product_id == product.id)
    )
    item = existing.scalar_one_or_none()
    new_qty = incoming + (item.qty if item is not None else Decimal("0"))
    amount = validate_cart_qty(catalog, new_qty)
    if item is None:
        session.add(CartItem(cart_id=cart.id, product_id=product.id, qty=amount))
    else:
        item.qty = amount
    await session.flush()
    return await get_cart(session, telegram_id)


async def set_cart_item(
    session: AsyncSession,
    telegram_id: int,
    sku: str,
    qty: Decimal | int | str,
    *,
    user_status: str,
) -> dict[str, object]:
    return await _save_line(session, telegram_id, sku, as_qty(qty), user_status=user_status)


async def remove_cart_item(
    session: AsyncSession,
    telegram_id: int,
    sku: str,
    *,
    user_status: str,
) -> dict[str, object]:
    ensure_active_user(user_status)
    cart_row = await session.execute(select(Cart).where(Cart.user_id == telegram_id))
    cart = cart_row.scalar_one_or_none()
    if cart is None:
        return cart_payload([])
    product_row = await session.execute(select(Product).where(Product.sku == sku))
    product = product_row.scalar_one_or_none()
    if product is None:
        raise DomainError("sku_not_found", "Товар не найден")
    existing = await session.execute(
        select(CartItem).where(CartItem.cart_id == cart.id, CartItem.product_id == product.id)
    )
    item = existing.scalar_one_or_none()
    if item is not None:
        await session.delete(item)
        await session.flush()
    return await get_cart(session, telegram_id)
