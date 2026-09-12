from pricebot.domain.errors import DomainError
from pricebot.domain.payments import OrderStatus

ADMIN_TRANSITIONS: frozenset[tuple[OrderStatus, OrderStatus]] = frozenset(
    {
        (OrderStatus.awaiting_payment, OrderStatus.cancelled),
        (OrderStatus.paid, OrderStatus.processing),
        (OrderStatus.processing, OrderStatus.done),
    }
)


def apply_admin_status(current: OrderStatus | str, target: OrderStatus | str) -> OrderStatus:
    now = current if isinstance(current, OrderStatus) else OrderStatus(current)
    wanted = target if isinstance(target, OrderStatus) else OrderStatus(target)
    if wanted is OrderStatus.paid:
        raise DomainError("paid_not_allowed", "Статус paid выставляет только платёжный модуль")
    if now is OrderStatus.done:
        raise DomainError("invalid_transition", "Недопустимый переход статуса")
    if wanted is OrderStatus.error:
        return OrderStatus.error
    if (now, wanted) not in ADMIN_TRANSITIONS:
        raise DomainError("invalid_transition", "Недопустимый переход статуса")
    return wanted
