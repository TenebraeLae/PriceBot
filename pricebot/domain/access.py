from collections.abc import Sequence

from pricebot.domain.errors import DomainError


def ensure_admin(telegram_id: int, admin_ids: Sequence[int]) -> None:
    if telegram_id not in admin_ids:
        raise DomainError("forbidden", "Недостаточно прав")


def ensure_active_user(status: str) -> None:
    if status == "blocked":
        raise DomainError("user_blocked", "Пользователь заблокирован")
