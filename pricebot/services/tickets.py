from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pricebot.config import Settings
from pricebot.db.models import SupportTicket
from pricebot.domain.checkout import MOSCOW, format_order_number, moscow_today
from pricebot.domain.errors import DomainError
from pricebot.services.notify import notify_ticket_created


async def _next_ticket_number(session: AsyncSession, now: datetime) -> str:
    day = moscow_today(now)
    prefix = f"T-{day:%Y%m%d}-"
    result = await session.execute(
        select(SupportTicket.ticket)
        .where(SupportTicket.ticket.like(f"{prefix}%"))
        .order_by(SupportTicket.ticket.desc())
        .limit(1)
    )
    last = result.scalar_one_or_none()
    seq = 1
    if last is not None:
        seq = int(last.rsplit("-", 1)[1]) + 1
    return f"T{format_order_number(day, seq)[2:]}"


async def create_ticket(
    session: AsyncSession,
    *,
    user_id: int,
    message: str,
    settings: Settings,
    now: datetime | None = None,
) -> SupportTicket:
    text = (message or "").strip()
    if not text:
        raise DomainError("ticket_empty", "Пустое обращение")
    current = now or datetime.now(MOSCOW)
    number = await _next_ticket_number(session, current)
    row = SupportTicket(ticket=number, user_id=user_id, message=text, status="open")
    session.add(row)
    await session.commit()
    await notify_ticket_created(settings, user_id, row.ticket, text)
    return row
