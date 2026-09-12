from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from pricebot.domain.errors import DomainError
from pricebot.domain.promo import PromoKind, PromoSpec, apply_promo, validate_promo

MOSCOW = ZoneInfo("Europe/Moscow")


def _promo(**overrides: object) -> PromoSpec:
    now = datetime(2026, 9, 12, 12, 0, tzinfo=MOSCOW)
    base = {
        "code": "SALE10",
        "kind": PromoKind.percent,
        "value": Decimal("10"),
        "starts_at": now - timedelta(days=1),
        "ends_at": now + timedelta(days=1),
        "max_uses": 5,
        "used_count": 0,
        "active": True,
    }
    base.update(overrides)
    return PromoSpec(**base)  # type: ignore[arg-type]


def test_percent_promo(now: datetime) -> None:
    total = apply_promo(Decimal("100.00"), _promo(), now=now)
    assert total == Decimal("90.00")


def test_invalid_expired_exhausted(now: datetime) -> None:
    with pytest.raises(DomainError) as expired:
        validate_promo(_promo(ends_at=now - timedelta(days=2)), now=now)
    with pytest.raises(DomainError) as exhausted:
        validate_promo(_promo(used_count=5, max_uses=5), now=now)
    with pytest.raises(DomainError) as inactive:
        validate_promo(_promo(active=False), now=now)
    with pytest.raises(DomainError) as missing:
        validate_promo(None, now=now)
    assert expired.value.code == "promo_expired"
    assert exhausted.value.code == "promo_exhausted"
    assert inactive.value.code == "promo_inactive"
    assert missing.value.code == "promo_invalid"


def test_fixed_greater_than_sum_clamps_to_zero(now: datetime) -> None:
    promo = _promo(kind=PromoKind.fixed, value=Decimal("999.00"))
    assert apply_promo(Decimal("100.00"), promo, now=now) == Decimal("0.00")
