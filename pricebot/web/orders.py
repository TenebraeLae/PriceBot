from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from pricebot.config import Settings
from pricebot.db.models import User
from pricebot.domain.access import ensure_active_user
from pricebot.domain.errors import DomainError
from pricebot.services.orders import (
    checkout_cart,
    checkout_json,
    list_user_orders,
    order_json,
    orders_json,
    qr_png_for_order,
)
from pricebot.web.deps import domain_http_error, get_session, get_settings_dep, require_webapp_user

router = APIRouter(prefix="/api/v1")


class CheckoutIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    telegram_id: int | None = Field(default=None)
    price: object | None = Field(default=None)
    promo_code: str | None = Field(default=None)


@router.post("/checkout")
async def post_checkout(
    body: CheckoutIn | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_webapp_user),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, object]:
    promo_code = body.promo_code if body is not None else None
    try:
        result = await checkout_cart(
            session,
            user_id=user.telegram_id,
            user_status=user.status,
            settings=settings,
            promo_code=promo_code,
        )
    except DomainError as exc:
        await session.rollback()
        raise domain_http_error(exc) from exc
    return checkout_json(result)


@router.get("/orders")
async def get_orders(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_webapp_user),
) -> dict[str, object]:
    try:
        ensure_active_user(user.status)
    except DomainError as exc:
        raise domain_http_error(exc) from exc
    orders = await list_user_orders(session, user.telegram_id)
    return orders_json(orders)


@router.get("/orders/{number}")
async def get_order(
    number: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_webapp_user),
) -> dict[str, object]:
    try:
        ensure_active_user(user.status)
        return await order_json(session, user.telegram_id, number, include_qr=True)
    except DomainError as exc:
        raise domain_http_error(exc) from exc


@router.get("/orders/{number}/qr")
async def get_order_qr(
    number: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_webapp_user),
) -> Response:
    try:
        ensure_active_user(user.status)
        png = await qr_png_for_order(session, user.telegram_id, number)
    except DomainError as exc:
        raise domain_http_error(exc) from exc
    return Response(content=png, media_type="image/png")
