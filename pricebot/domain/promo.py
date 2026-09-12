from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from zoneinfo import ZoneInfo

from pricebot.domain.errors import DomainError

MOSCOW = ZoneInfo("Europe/Moscow")


class PromoKind(str, Enum):
    percent = "percent"
    fixed = "fixed"


@dataclass(frozen=True)
class PromoSpec:
    code: str
    kind: PromoKind
    value: Decimal
    starts_at: datetime
    ends_at: datetime
    max_uses: int | None = None
    used_count: int = 0
    active: bool = True


def _as_moscow(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=MOSCOW)
    return moment.astimezone(MOSCOW)


def validate_promo(promo: PromoSpec | None, *, now: datetime) -> PromoSpec:
    if promo is None:
        raise DomainError("promo_invalid", "Промокод неверен")
    current = _as_moscow(now)
    start = _as_moscow(promo.starts_at)
    end = _as_moscow(promo.ends_at)
    if not promo.active:
        raise DomainError("promo_inactive", "Промокод неактивен")
    if current < start or current > end:
        raise DomainError("promo_expired", "Промокод просрочен или ещё не действует")
    if promo.max_uses is not None and promo.used_count >= promo.max_uses:
        raise DomainError("promo_exhausted", "Лимит использований промокода исчерпан")
    return promo


def apply_promo(subtotal: Decimal, promo: PromoSpec, *, now: datetime) -> Decimal:
    validate_promo(promo, now=now)
    if promo.kind is PromoKind.percent:
        discount = (subtotal * promo.value / Decimal("100")).quantize(Decimal("0.01"))
    else:
        discount = promo.value.quantize(Decimal("0.01"))
    total = subtotal - discount
    if total < 0:
        return Decimal("0.00")
    return total.quantize(Decimal("0.01"))
