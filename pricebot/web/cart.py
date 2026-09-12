from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from pricebot.db.models import User
from pricebot.domain.access import ensure_active_user
from pricebot.domain.errors import DomainError
from pricebot.services.cart import add_cart_item, get_cart, remove_cart_item, set_cart_item
from pricebot.web.deps import domain_http_error, get_session, require_webapp_user

router = APIRouter(prefix="/api/v1")


class CartItemIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sku: str
    qty: Decimal
    price: Decimal | None = Field(default=None)
    telegram_id: int | None = Field(default=None)


class CartQtyIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    qty: Decimal
    price: Decimal | None = Field(default=None)
    telegram_id: int | None = Field(default=None)


@router.get("/cart")
async def read_cart(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_webapp_user),
) -> dict[str, object]:
    try:
        ensure_active_user(user.status)
    except DomainError as exc:
        raise domain_http_error(exc) from exc
    return await get_cart(session, user.telegram_id)


@router.post("/cart/items")
async def post_cart_item(
    body: CartItemIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_webapp_user),
) -> dict[str, object]:
    try:
        payload = await add_cart_item(
            session,
            user.telegram_id,
            body.sku,
            body.qty,
            user_status=user.status,
        )
        await session.commit()
    except DomainError as exc:
        await session.rollback()
        raise domain_http_error(exc) from exc
    return payload


@router.put("/cart/items/{sku}")
async def put_cart_item(
    sku: str,
    body: CartQtyIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_webapp_user),
) -> dict[str, object]:
    try:
        payload = await set_cart_item(
            session,
            user.telegram_id,
            sku,
            body.qty,
            user_status=user.status,
        )
        await session.commit()
    except DomainError as exc:
        await session.rollback()
        raise domain_http_error(exc) from exc
    return payload


@router.delete("/cart/items/{sku}")
async def delete_cart_item(
    sku: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_webapp_user),
) -> dict[str, object]:
    try:
        payload = await remove_cart_item(
            session,
            user.telegram_id,
            sku,
            user_status=user.status,
        )
        await session.commit()
    except DomainError as exc:
        await session.rollback()
        raise domain_http_error(exc) from exc
    return payload
