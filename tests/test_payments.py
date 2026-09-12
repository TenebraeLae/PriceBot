from decimal import Decimal
from pathlib import Path

import pytest

from pricebot.domain.errors import DomainError
from pricebot.domain.payments import (
    FakePaymentProvider,
    OrderStatus,
    PaymentDraft,
    PaymentStatus,
    apply_payment_webhook,
    dumps_webhook,
    ensure_single_payment,
    order_status_label,
    require_not_paid_without_fact,
    sign_payload,
)
from pricebot.domain.yookassa import YooKassaPaymentProvider
from pricebot.services.orders import payment_provider
from tests.conftest import make_test_settings


def test_order_status_russian() -> None:
    assert order_status_label(OrderStatus.awaiting_payment) == "ожидает оплаты"
    assert order_status_label("paid") == "оплачен"


def test_without_webhook_stays_awaiting() -> None:
    assert OrderStatus.awaiting_payment.value == "awaiting_payment"
    require_not_paid_without_fact(OrderStatus.awaiting_payment, payment_succeeded=False)
    with pytest.raises(DomainError) as err:
        require_not_paid_without_fact(OrderStatus.paid, payment_succeeded=False)
    assert err.value.code == "payment_required"


def test_bad_signature_does_not_change() -> None:
    event = FakePaymentProvider().parse_webhook(
        {"provider_payment_id": "p1", "amount": "100.00", "status": "succeeded"}
    )
    result = apply_payment_webhook(
        order_status=OrderStatus.awaiting_payment,
        order_total=Decimal("100.00"),
        payment_status=PaymentStatus.created,
        event=event,
        signature_valid=False,
        seen_ids=set(),
    )
    assert result.http_status == 401
    assert result.order_status is OrderStatus.awaiting_payment
    assert result.payment_status is PaymentStatus.created
    assert result.accepted is False


def test_success_then_replay_idempotent() -> None:
    provider = FakePaymentProvider(secret="s")
    body = {"provider_payment_id": "fake-PB-1", "amount": "100.00", "status": "succeeded"}
    event = provider.parse_webhook(body)
    seen: set[str] = set()
    first = apply_payment_webhook(
        order_status=OrderStatus.awaiting_payment,
        order_total=Decimal("100.00"),
        payment_status=PaymentStatus.created,
        event=event,
        signature_valid=True,
        seen_ids=seen,
    )
    replay = apply_payment_webhook(
        order_status=first.order_status,
        order_total=Decimal("100.00"),
        payment_status=first.payment_status,
        event=event,
        signature_valid=True,
        seen_ids=seen,
    )
    assert first.order_status is OrderStatus.paid
    assert first.payment_status is PaymentStatus.succeeded
    assert replay.noop is True
    assert replay.order_status is OrderStatus.paid
    assert sign_payload(dumps_webhook(body), "s")


def test_amount_mismatch_is_error_not_paid() -> None:
    event = FakePaymentProvider().parse_webhook(
        {"provider_payment_id": "p2", "amount": "50.00", "status": "succeeded"}
    )
    result = apply_payment_webhook(
        order_status=OrderStatus.awaiting_payment,
        order_total=Decimal("100.00"),
        payment_status=PaymentStatus.created,
        event=event,
        signature_valid=True,
        seen_ids=set(),
    )
    assert result.order_status is OrderStatus.error
    assert result.payment_status is PaymentStatus.failed


def test_double_tap_one_payment() -> None:
    provider = FakePaymentProvider()
    first = ensure_single_payment(None, provider, "PB-1", Decimal("10.00"))
    second = ensure_single_payment(first, provider, "PB-1", Decimal("10.00"))
    assert first is second
    assert first.payload.startswith("https://pay.local/")
    assert isinstance(first, PaymentDraft)


def test_factory_selects_fake_by_default(tmp_path: Path) -> None:
    settings = make_test_settings(tmp_path)
    assert settings.payment_provider == "fake"
    assert isinstance(payment_provider(settings), FakePaymentProvider)


def test_factory_selects_yookassa(tmp_path: Path) -> None:
    settings = make_test_settings(tmp_path).model_copy(
        update={
            "payment_provider": "yookassa",
            "yookassa_shop_id": "shop",
            "yookassa_secret_key": "secret",
        }
    )
    provider = payment_provider(settings)
    assert isinstance(provider, YooKassaPaymentProvider)
    assert provider.return_url.endswith("/app/")


def test_factory_yookassa_requires_keys(tmp_path: Path) -> None:
    settings = make_test_settings(tmp_path).model_copy(update={"payment_provider": "yookassa"})
    with pytest.raises(DomainError) as err:
        payment_provider(settings)
    assert err.value.code == "yookassa_config"
