from __future__ import annotations

import ipaddress
import json
import uuid
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import httpx

from pricebot.domain.errors import DomainError
from pricebot.domain.payments import PaymentDraft, PaymentStatus, WebhookEvent

YOOKASSA_API = "https://api.yookassa.ru/v3"

# Official notification source networks (no HMAC).
DEFAULT_YOOKASSA_NETWORKS: tuple[str, ...] = (
    "185.71.76.0/27",
    "185.71.77.0/27",
    "77.75.153.0/25",
    "77.75.156.11/32",
    "77.75.156.35/32",
    "77.75.154.128/25",
    "2a02:5180::/32",
)


def map_yookassa_status(status: str) -> PaymentStatus:
    key = (status or "").strip().lower()
    if key == "succeeded":
        return PaymentStatus.succeeded
    if key in {"canceled", "cancelled"}:
        return PaymentStatus.failed
    if key == "expired":
        return PaymentStatus.expired
    if key in {"pending", "waiting_for_capture"}:
        return PaymentStatus.pending
    return PaymentStatus.pending


def parse_trusted_ips(raw: str) -> list[str] | None:
    text = (raw or "").strip()
    if text == "*":
        return None
    if not text:
        return list(DEFAULT_YOOKASSA_NETWORKS)
    return [part.strip() for part in text.split(",") if part.strip()]


def ip_allowed(client_ip: str, trusted: Sequence[str] | None) -> bool:
    if trusted is None:
        return True
    if not client_ip:
        return False
    try:
        addr = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    for item in trusted:
        token = item.strip()
        if not token:
            continue
        if token == "*":
            return True
        try:
            if "/" in token:
                if addr in ipaddress.ip_network(token, strict=False):
                    return True
            elif addr == ipaddress.ip_address(token):
                return True
        except ValueError:
            continue
    return False


def default_return_url(public_base_url: str, override: str = "") -> str:
    text = (override or "").strip()
    if text:
        return text
    return f"{public_base_url.rstrip('/')}/app/"


class YooKassaPaymentProvider:
    name = "yookassa"

    def __init__(
        self,
        shop_id: str,
        secret_key: str,
        return_url: str,
        *,
        trusted_ips: Sequence[str] | None = DEFAULT_YOOKASSA_NETWORKS,
        client: Any | None = None,
    ) -> None:
        self.shop_id = shop_id
        self.secret_key = secret_key
        self.return_url = return_url
        self.trusted_ips = None if trusted_ips is None else list(trusted_ips)
        self._client = client or httpx.Client(timeout=20.0)

    def create_payment(self, order_number: str, amount: Decimal) -> PaymentDraft:
        value = f"{amount.quantize(Decimal('0.01')):.2f}"
        response = self._client.post(
            f"{YOOKASSA_API}/payments",
            json={
                "amount": {"value": value, "currency": "RUB"},
                "capture": True,
                "confirmation": {"type": "redirect", "return_url": self.return_url},
                "description": order_number,
                "metadata": {"order_number": order_number},
            },
            auth=(self.shop_id, self.secret_key),
            headers={
                "Idempotence-Key": str(uuid.uuid4()),
                "Content-Type": "application/json",
            },
        )
        self._raise_http(response, "yookassa_create")
        data = response.json()
        url = str((data.get("confirmation") or {}).get("confirmation_url") or "").strip()
        if not url:
            raise DomainError("empty_payment_payload", "Пустой confirmation_url ЮKassa")
        payment_id = str(data.get("id") or "").strip()
        if not payment_id:
            raise DomainError("empty_payment_id", "Пустой id платежа ЮKassa")
        return PaymentDraft(
            provider=self.name,
            provider_payment_id=payment_id,
            amount=amount,
            payload=url,
            status=PaymentStatus.created,
        )

    def get_status(self, provider_payment_id: str) -> PaymentStatus:
        data = self._fetch_payment(provider_payment_id)
        return map_yookassa_status(str(data.get("status") or "pending"))

    def parse_webhook(self, body: dict[str, Any]) -> WebhookEvent:
        obj = body.get("object")
        if not isinstance(obj, dict):
            raise DomainError("bad_webhook", "Нет object в уведомлении ЮKassa")
        payment_id = str(obj.get("id") or "").strip()
        amount_raw = (obj.get("amount") or {}).get("value")
        if not payment_id or amount_raw in (None, ""):
            raise DomainError("bad_webhook", "Некорректное уведомление ЮKassa")
        return WebhookEvent(
            provider_payment_id=payment_id,
            amount=Decimal(str(amount_raw)),
            status=map_yookassa_status(str(obj.get("status") or "pending")),
        )

    def verify_signature(self, body: bytes, signature: str) -> bool:
        del body, signature
        return False

    def verify_notification(self, client_ip: str, body: bytes) -> bool:
        if not ip_allowed(client_ip, self.trusted_ips):
            return False
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False
        obj = parsed.get("object") if isinstance(parsed, dict) else None
        if not isinstance(obj, dict):
            return False
        payment_id = str(obj.get("id") or "").strip()
        if not payment_id:
            return False
        try:
            remote = self._fetch_payment(payment_id)
        except DomainError:
            return False
        if str(remote.get("id") or "") != payment_id:
            return False
        local_amount = str((obj.get("amount") or {}).get("value") or "")
        remote_amount = str((remote.get("amount") or {}).get("value") or "")
        if local_amount and remote_amount and local_amount != remote_amount:
            return False
        return True

    def _fetch_payment(self, provider_payment_id: str) -> dict[str, Any]:
        response = self._client.get(
            f"{YOOKASSA_API}/payments/{provider_payment_id}",
            auth=(self.shop_id, self.secret_key),
        )
        self._raise_http(response, "yookassa_get")
        data = response.json()
        if not isinstance(data, dict):
            raise DomainError("yookassa_get", "Некорректный ответ ЮKassa")
        return data

    def _raise_http(self, response: Any, code: str) -> None:
        status = int(getattr(response, "status_code", 0) or 0)
        if 200 <= status < 300:
            return
        raise DomainError(code, "Ошибка ЮKassa")
