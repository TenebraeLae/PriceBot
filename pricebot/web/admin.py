from decimal import Decimal
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from pricebot.config import Settings
from pricebot.domain.errors import DomainError
from pricebot.services.admin import (
    _order_admin_payload,
    create_promo,
    disable_promo,
    export_catalog_bytes,
    list_admin_tickets,
    list_admin_users,
    promo_json,
    reply_ticket,
    search_admin_orders,
    set_admin_order_status,
    set_user_blocked,
    ticket_json,
    user_json,
)
from pricebot.services.import_catalog import apply_price_import
from pricebot.web.deps import domain_http_error, get_session, get_settings_dep, require_admin

router = APIRouter(prefix="/api/v1")


class StatusIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str


class PromoIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str
    kind: str
    value: Decimal
    starts_at: datetime
    ends_at: datetime
    max_uses: int | None = None
    active: bool = True


class TicketReplyIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str = Field(min_length=1)


@router.post("/admin/import")
async def admin_import(
    file: UploadFile = File(...),
    admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, object]:
    filename = file.filename or "price.xlsx"
    if not filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Нужен файл .xlsx")
    content = await file.read()
    report = await apply_price_import(
        session,
        content=content,
        filename=filename,
        admin_id=admin_id,
        admin_ids=settings.admin_ids,
        imports_dir=settings.imports_dir,
        max_rows=settings.max_import_rows,
        timezone_name=settings.timezone,
        redis_url=settings.redis_url,
    )
    return {
        "status": report.status,
        "rows_ok": report.rows_ok,
        "rows_err": report.rows_err,
        "reject_reason": report.reject_reason,
        "import_id": report.import_id,
        "errors": [{"row": err.row, "message": err.message} for err in report.errors],
    }


@router.get("/admin/orders")
async def admin_orders(
    number: str | None = Query(default=None),
    telegram_id: int | None = Query(default=None),
    sku: str | None = Query(default=None),
    status: str | None = Query(default=None),
    _admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    orders = await search_admin_orders(
        session, number=number, telegram_id=telegram_id, sku=sku, status=status
    )
    return {"items": [_order_admin_payload(order) for order in orders]}


@router.post("/admin/orders/{number}/status")
async def admin_order_status(
    number: str,
    body: StatusIn,
    _admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, object]:
    try:
        order = await set_admin_order_status(
            session, number=number, status=body.status, settings=settings
        )
    except DomainError as exc:
        await session.rollback()
        raise domain_http_error(exc) from exc
    return _order_admin_payload(order)


@router.get("/admin/users")
async def admin_users(
    _admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    return {"items": [user_json(user) for user in await list_admin_users(session)]}


@router.post("/admin/users/{telegram_id}/block")
async def admin_block_user(
    telegram_id: int,
    _admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    try:
        user = await set_user_blocked(session, telegram_id, blocked=True)
    except DomainError as exc:
        await session.rollback()
        raise domain_http_error(exc) from exc
    return user_json(user)


@router.post("/admin/users/{telegram_id}/unblock")
async def admin_unblock_user(
    telegram_id: int,
    _admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    try:
        user = await set_user_blocked(session, telegram_id, blocked=False)
    except DomainError as exc:
        await session.rollback()
        raise domain_http_error(exc) from exc
    return user_json(user)


@router.post("/admin/promos")
async def admin_create_promo(
    body: PromoIn,
    _admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    try:
        promo = await create_promo(
            session,
            code=body.code,
            kind=body.kind,
            value=body.value,
            starts_at=body.starts_at,
            ends_at=body.ends_at,
            max_uses=body.max_uses,
            active=body.active,
        )
    except DomainError as exc:
        await session.rollback()
        raise domain_http_error(exc) from exc
    return promo_json(promo)


@router.post("/admin/promos/{code}/disable")
async def admin_disable_promo(
    code: str,
    _admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    try:
        promo = await disable_promo(session, code)
    except DomainError as exc:
        await session.rollback()
        raise domain_http_error(exc) from exc
    return promo_json(promo)


@router.get("/admin/tickets")
async def admin_tickets(
    status: str = Query(default="open"),
    _admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    rows = await list_admin_tickets(session, status=status)
    return {"items": [ticket_json(row) for row in rows]}


@router.post("/admin/tickets/{ticket}/reply")
async def admin_ticket_reply(
    ticket: str,
    body: TicketReplyIn,
    _admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, object]:
    try:
        row = await reply_ticket(session, ticket=ticket, text=body.text, settings=settings)
    except DomainError as exc:
        await session.rollback()
        raise domain_http_error(exc) from exc
    return ticket_json(row)


@router.get("/admin/catalog.xlsx")
async def admin_catalog_export(
    _admin_id: int = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> Response:
    content = await export_catalog_bytes(session)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="catalog.xlsx"'},
    )
