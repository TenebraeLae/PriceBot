from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from pricebot.config import Settings
from pricebot.db.models import User
from pricebot.domain.errors import DomainError
from pricebot.services.admin import ticket_json
from pricebot.services.tickets import create_ticket
from pricebot.web.deps import domain_http_error, get_session, get_settings_dep, require_webapp_user

router = APIRouter(prefix="/api/v1")


class TicketIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str = Field(min_length=1)


@router.post("/tickets")
async def post_ticket(
    body: TicketIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_webapp_user),
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, object]:
    try:
        row = await create_ticket(
            session, user_id=user.telegram_id, message=body.text, settings=settings
        )
    except DomainError as exc:
        await session.rollback()
        raise domain_http_error(exc) from exc
    return ticket_json(row)
