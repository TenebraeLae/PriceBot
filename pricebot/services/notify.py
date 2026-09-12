from dataclasses import dataclass, field
from typing import Protocol

from pricebot.config import Settings
from pricebot.domain.payments import order_status_label


@dataclass(frozen=True)
class Notice:
    kind: str
    chat_id: int
    text: str
    order_number: str


class Notifier(Protocol):
    async def send(self, chat_id: int, text: str) -> None: ...


class RecordingNotifier:
    def __init__(self) -> None:
        self.sent: list[Notice] = []

    async def send(self, chat_id: int, text: str) -> None:
        del chat_id, text


class TelegramNotifier:
    def __init__(self, token: str) -> None:
        self.token = token

    async def send(self, chat_id: int, text: str) -> None:
        import asyncio

        from aiogram.exceptions import TelegramAPIError

        from pricebot.bot.session import make_bot
        from pricebot.domain.telegram import call_with_retry

        bot = make_bot(self.token)
        try:
            await call_with_retry(
                lambda: bot.send_message(chat_id, text),
                sleeper=asyncio.sleep,
            )
        except (TelegramAPIError, OSError):
            return
        finally:
            await bot.session.close()


@dataclass
class NotificationLog:
    events: list[Notice] = field(default_factory=list)

    def emit(self, kind: str, chat_id: int, text: str, order_number: str) -> None:
        self.events.append(
            Notice(kind=kind, chat_id=chat_id, text=text, order_number=order_number)
        )

    def reset(self) -> None:
        self.events.clear()

    def count(self, *, kind: str | None = None, order_number: str | None = None) -> int:
        total = 0
        for event in self.events:
            if kind is not None and event.kind != kind:
                continue
            if order_number is not None and event.order_number != order_number:
                continue
            total += 1
        return total


_log = NotificationLog()
_notifier: Notifier = RecordingNotifier()


def get_notification_log() -> NotificationLog:
    return _log


def set_notifier(notifier: Notifier) -> None:
    global _notifier
    _notifier = notifier


def get_notifier() -> Notifier:
    return _notifier


def reset_notifications() -> None:
    _log.reset()
    set_notifier(RecordingNotifier())


async def notify_order_created(settings: Settings, user_id: int, number: str, total: str) -> None:
    user_text = f"Заказ {number} создан. Сумма {total} ₽. Ожидает оплаты."
    _log.emit("order_created", user_id, user_text, number)
    await _notifier.send(user_id, user_text)
    admin_text = f"Новый заказ {number} на {total} ₽."
    for admin_id in settings.admin_ids:
        _log.emit("admin_new_order", admin_id, admin_text, number)
        await _notifier.send(admin_id, admin_text)


async def notify_order_paid(settings: Settings, user_id: int, number: str) -> None:
    user_text = f"Заказ {number} оплачен."
    _log.emit("order_paid", user_id, user_text, number)
    await _notifier.send(user_id, user_text)
    admin_text = f"Оплата заказа {number} получена."
    for admin_id in settings.admin_ids:
        _log.emit("admin_paid", admin_id, admin_text, number)
        await _notifier.send(admin_id, admin_text)


async def notify_order_error(settings: Settings, user_id: int, number: str) -> None:
    user_text = f"Заказ {number}: ошибка оплаты."
    _log.emit("order_error", user_id, user_text, number)
    await _notifier.send(user_id, user_text)


async def notify_order_status(
    settings: Settings, user_id: int, number: str, status: str
) -> None:
    del settings
    label = order_status_label(status)
    user_text = f"Заказ {number}: {label}."
    _log.emit(f"order_{status}", user_id, user_text, number)
    await _notifier.send(user_id, user_text)


async def notify_ticket_reply(
    settings: Settings, user_id: int, ticket: str, text: str
) -> None:
    del settings
    user_text = f"Ответ по обращению {ticket}:\n{text}"
    _log.emit("ticket_reply", user_id, user_text, ticket)
    await _notifier.send(user_id, user_text)


async def notify_ticket_created(
    settings: Settings, user_id: int, ticket: str, message: str
) -> None:
    user_text = f"Обращение {ticket} принято."
    _log.emit("ticket_created", user_id, user_text, ticket)
    await _notifier.send(user_id, user_text)
    admin_text = f"Новое обращение {ticket} от {user_id}: {message}"
    for admin_id in settings.admin_ids:
        _log.emit("admin_ticket", admin_id, admin_text, ticket)
        await _notifier.send(admin_id, admin_text)
