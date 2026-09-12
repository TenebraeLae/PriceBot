from decimal import Decimal

import pytest

from pricebot.domain.errors import DomainError
from pricebot.domain.payments import PaymentStatus
from pricebot.domain.yookassa import YooKassaPaymentProvider, map_yookassa_status


class _Resp:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload


class _MockClient:
    def __init__(self, payment: dict) -> None:
        self.payment = payment
        self.posts: list[dict] = []
        self.gets: list[dict] = []

    def post(self, url, json=None, auth=None, headers=None):
        self.posts.append({"url": url, "json": json, "auth": auth, "headers": headers})
        return _Resp(self.payment)

    def get(self, url, auth=None):
        self.gets.append({"url": url, "auth": auth})
        return _Resp(self.payment)


def _payment(**extra) -> dict:
    data = {
        "id": "pay_1",
        "status": "pending",
        "amount": {"value": "10.00", "currency": "RUB"},
        "confirmation": {"type": "redirect", "confirmation_url": "https://yoomoney.ru/checkout/pay_1"},
    }
    data.update(extra)
    return data


def test_map_yookassa_statuses() -> None:
    assert map_yookassa_status("succeeded") is PaymentStatus.succeeded
    assert map_yookassa_status("canceled") is PaymentStatus.failed
    assert map_yookassa_status("pending") is PaymentStatus.pending
    assert map_yookassa_status("waiting_for_capture") is PaymentStatus.pending


def test_create_payment_uses_official_api() -> None:
    client = _MockClient(_payment())
    provider = YooKassaPaymentProvider(
        "shopId",
        "secret",
        "https://shop.example/app/",
        trusted_ips=["127.0.0.1"],
        client=client,
    )
    draft = provider.create_payment("PB-20260912-0001", Decimal("10.00"))
    assert draft.provider == "yookassa"
    assert draft.provider_payment_id == "pay_1"
    assert draft.payload == "https://yoomoney.ru/checkout/pay_1"
    posted = client.posts[0]
    assert posted["url"] == "https://api.yookassa.ru/v3/payments"
    assert posted["auth"] == ("shopId", "secret")
    assert posted["headers"]["Idempotence-Key"]
    assert posted["json"]["amount"] == {"value": "10.00", "currency": "RUB"}
    assert posted["json"]["capture"] is True
    assert posted["json"]["confirmation"]["type"] == "redirect"


def test_create_payment_requires_confirmation_url() -> None:
    client = _MockClient(_payment(confirmation={"type": "redirect"}))
    provider = YooKassaPaymentProvider("s", "k", "https://x/app/", client=client)
    with pytest.raises(DomainError) as err:
        provider.create_payment("PB-1", Decimal("1.00"))
    assert err.value.code == "empty_payment_payload"


def test_parse_webhook_and_get_status() -> None:
    client = _MockClient(_payment(status="succeeded"))
    provider = YooKassaPaymentProvider("s", "k", "https://x/app/", client=client)
    event = provider.parse_webhook(
        {
            "type": "notification",
            "event": "payment.succeeded",
            "object": {
                "id": "pay_1",
                "status": "succeeded",
                "amount": {"value": "10.00"},
            },
        }
    )
    assert event.provider_payment_id == "pay_1"
    assert event.amount == Decimal("10.00")
    assert event.status is PaymentStatus.succeeded
    assert provider.get_status("pay_1") is PaymentStatus.succeeded
    assert client.gets[0]["url"] == "https://api.yookassa.ru/v3/payments/pay_1"


def test_verify_notification_ip_and_refetch() -> None:
    client = _MockClient(_payment(status="succeeded"))
    provider = YooKassaPaymentProvider(
        "s",
        "k",
        "https://x/app/",
        trusted_ips=["185.71.76.0/27"],
        client=client,
    )
    body = (
        b'{"object":{"id":"pay_1","status":"succeeded","amount":{"value":"10.00"}}}'
    )
    assert provider.verify_notification("185.71.76.10", body) is True
    assert provider.verify_notification("8.8.8.8", body) is False
    assert provider.verify_signature(body, "") is False
