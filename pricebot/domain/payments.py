from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import MutableSet
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any, Protocol

from pricebot.domain.errors import DomainError


class OrderStatus(str, Enum):
    awaiting_payment = "awaiting_payment"
    paid = "paid"
    processing = "processing"
    done = "done"
    cancelled = "cancelled"
    error = "error"


class PaymentStatus(str, Enum):
    created = "created"
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"
    expired = "expired"


ORDER_STATUS_RU: dict[OrderStatus, str] = {
    OrderStatus.awaiting_payment: "ожидает оплаты",
    OrderStatus.paid: "оплачен",
    OrderStatus.processing: "в обработке",
    OrderStatus.done: "выполнен",
    OrderStatus.cancelled: "отменён",
    OrderStatus.error: "ошибка",
}


def order_status_label(status: OrderStatus | str) -> str:
    key = status if isinstance(status, OrderStatus) else OrderStatus(status)
    return ORDER_STATUS_RU[key]


@dataclass(frozen=True)
class PaymentDraft:
    provider: str
    provider_payment_id: str
    amount: Decimal
    payload: str
    status: PaymentStatus = PaymentStatus.created


@dataclass(frozen=True)
class WebhookEvent:
    provider_payment_id: str
    amount: Decimal
    status: PaymentStatus


@dataclass(frozen=True)
class WebhookApplyResult:
    accepted: bool
    noop: bool
    http_status: int
    order_status: OrderStatus
    payment_status: PaymentStatus


class PaymentProvider(Protocol):
    def create_payment(self, order_number: str, amount: Decimal) -> PaymentDraft: ...

    def get_status(self, provider_payment_id: str) -> PaymentStatus: ...

    def parse_webhook(self, body: dict[str, Any]) -> WebhookEvent: ...

    def verify_signature(self, body: bytes, signature: str) -> bool: ...


def sign_payload(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


class FakePaymentProvider:
    name = "fake"

    def __init__(self, secret: str = "test-secret") -> None:
        self.secret = secret
        self._statuses: dict[str, PaymentStatus] = {}

    def create_payment(self, order_number: str, amount: Decimal) -> PaymentDraft:
        provider_payment_id = f"fake-{order_number}"
        payload = f"https://pay.local/{provider_payment_id}"
        self._statuses[provider_payment_id] = PaymentStatus.created
        return PaymentDraft(
            provider=self.name,
            provider_payment_id=provider_payment_id,
            amount=amount,
            payload=payload,
        )

    def get_status(self, provider_payment_id: str) -> PaymentStatus:
        return self._statuses.get(provider_payment_id, PaymentStatus.expired)

    def parse_webhook(self, body: dict[str, Any]) -> WebhookEvent:
        return WebhookEvent(
            provider_payment_id=str(body["provider_payment_id"]),
            amount=Decimal(str(body["amount"])),
            status=PaymentStatus(body.get("status", "succeeded")),
        )

    def verify_signature(self, body: bytes, signature: str) -> bool:
        expected = sign_payload(body, self.secret)
        return hmac.compare_digest(expected, signature or "")


def ensure_single_payment(
    existing: PaymentDraft | None,
    factory: PaymentProvider,
    order_number: str,
    amount: Decimal,
) -> PaymentDraft:
    if existing is not None:
        return existing
    return factory.create_payment(order_number, amount)


def apply_payment_webhook(
    *,
    order_status: OrderStatus,
    order_total: Decimal,
    payment_status: PaymentStatus,
    event: WebhookEvent,
    signature_valid: bool,
    seen_ids: MutableSet[str],
) -> WebhookApplyResult:
    if not signature_valid:
        return WebhookApplyResult(
            accepted=False,
            noop=False,
            http_status=401,
            order_status=order_status,
            payment_status=payment_status,
        )
    if event.provider_payment_id in seen_ids:
        return WebhookApplyResult(
            accepted=True,
            noop=True,
            http_status=200,
            order_status=order_status,
            payment_status=payment_status,
        )
    seen_ids.add(event.provider_payment_id)
    if event.amount.quantize(Decimal("0.01")) != order_total.quantize(Decimal("0.01")):
        return WebhookApplyResult(
            accepted=True,
            noop=False,
            http_status=200,
            order_status=OrderStatus.error,
            payment_status=PaymentStatus.failed,
        )
    return WebhookApplyResult(
        accepted=True,
        noop=False,
        http_status=200,
        order_status=OrderStatus.paid,
        payment_status=PaymentStatus.succeeded,
    )


def dumps_webhook(body: dict[str, Any]) -> bytes:
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def require_not_paid_without_fact(status: OrderStatus, payment_succeeded: bool) -> None:
    if status is OrderStatus.paid and not payment_succeeded:
        raise DomainError("payment_required", "Заказ не оплачен")
