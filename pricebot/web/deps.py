from collections.abc import AsyncIterator

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from pricebot.config import Settings, get_settings
from pricebot.db.models import User
from pricebot.db.session import make_engine, make_session_factory
from pricebot.domain.access import ensure_admin
from pricebot.domain.errors import DomainError
from pricebot.services.users import upsert_user
from pricebot.web.auth import InitDataError, validate_init_data

_session_factory = None


def get_settings_dep() -> Settings:
    return get_settings()


def set_session_factory(factory) -> None:
    global _session_factory
    _session_factory = factory


def reset_session_factory() -> None:
    global _session_factory
    _session_factory = None


def _factory():
    global _session_factory
    if _session_factory is None:
        engine = make_engine(get_settings().database_url)
        _session_factory = make_session_factory(engine)
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    factory = _factory()
    async with factory() as session:
        yield session


async def require_admin(
    settings: Settings = Depends(get_settings_dep),
    x_telegram_id: int | None = Header(default=None, alias="X-Telegram-Id"),
) -> int:
    if x_telegram_id is None:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    try:
        ensure_admin(x_telegram_id, settings.admin_ids)
    except DomainError as exc:
        raise HTTPException(status_code=403, detail=exc.message) from exc
    return x_telegram_id


async def require_webapp_user(
    settings: Settings = Depends(get_settings_dep),
    session: AsyncSession = Depends(get_session),
    x_telegram_init_data: str | None = Header(default=None, alias="X-Telegram-Init-Data"),
) -> User:
    try:
        verified = validate_init_data(x_telegram_init_data, settings.bot_token)
    except InitDataError as exc:
        raise HTTPException(status_code=401, detail="Недействительные данные Telegram") from exc
    user = await upsert_user(session, verified.telegram_id, verified.username)
    await session.commit()
    return user


def domain_http_error(exc: DomainError) -> HTTPException:
    if exc.code == "user_blocked":
        return HTTPException(status_code=403, detail=exc.message)
    if exc.code in {
        "sku_not_found",
        "order_not_found",
        "payment_not_found",
        "user_not_found",
        "ticket_not_found",
    }:
        return HTTPException(status_code=404, detail=exc.message)
    return HTTPException(status_code=400, detail=exc.message)
