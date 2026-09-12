from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from pricebot.config import Settings
from pricebot.domain.errors import DomainError
from pricebot.services.orders import apply_webhook_bytes
from pricebot.web.deps import domain_http_error, get_session, get_settings_dep

router = APIRouter(prefix="/api/v1")


def request_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client is not None:
        return request.client.host
    return ""


async def _handle_webhook(
    request: Request,
    session: AsyncSession,
    settings: Settings,
    signature: str | None,
) -> dict[str, object]:
    body = await request.body()
    try:
        result = await apply_webhook_bytes(
            session,
            settings=settings,
            body=body,
            signature=signature or "",
            client_ip=request_client_ip(request),
        )
    except DomainError as exc:
        await session.rollback()
        raise domain_http_error(exc) from exc
    if result.get("http_status") == 401:
        raise HTTPException(status_code=401, detail=str(result.get("detail") or "Недействительная подпись"))
    return {key: value for key, value in result.items() if key != "http_status"}


@router.post("/payments/webhook")
async def payment_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings_dep),
    x_payment_signature: str | None = Header(default=None, alias="X-Payment-Signature"),
) -> dict[str, object]:
    return await _handle_webhook(request, session, settings, x_payment_signature)


@router.post("/payments/fake/webhook")
async def fake_payment_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings_dep),
    x_payment_signature: str | None = Header(default=None, alias="X-Payment-Signature"),
) -> dict[str, object]:
    return await _handle_webhook(request, session, settings, x_payment_signature)
