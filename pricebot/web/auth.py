from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl

INIT_DATA_MAX_AGE_SECONDS = 86_400
_CLOCK_SKEW_SECONDS = 300


class InitDataError(Exception):
    """Invalid or missing Telegram Mini App initData."""


@dataclass(frozen=True)
class VerifiedWebApp:
    telegram_id: int
    username: str | None


def constant_time_equal(left: str, right: str) -> bool:
    left_bytes = left.encode("utf-8")
    right_bytes = right.encode("utf-8")
    if len(left_bytes) != len(right_bytes):
        hmac.compare_digest(right_bytes, right_bytes)
        return False
    return hmac.compare_digest(left_bytes, right_bytes)


def validate_init_data(
    init_data: str | None,
    bot_token: str,
    *,
    now: float | None = None,
    max_age_seconds: int = INIT_DATA_MAX_AGE_SECONDS,
) -> VerifiedWebApp:
    raw = (init_data or "").strip()
    if not raw:
        raise InitDataError("missing")
    pairs = dict(parse_qsl(raw, keep_blank_values=True))
    received_hash = pairs.pop("hash", "")
    if not received_hash:
        raise InitDataError("missing_hash")
    data_check = "\n".join(f"{key}={value}" for key, value in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    computed = hmac.new(secret, data_check.encode("utf-8"), hashlib.sha256).hexdigest()
    if not constant_time_equal(computed, received_hash):
        raise InitDataError("bad_hash")
    try:
        auth_date = int(pairs.get("auth_date") or "")
    except ValueError as exc:
        raise InitDataError("bad_auth_date") from exc
    age = (time.time() if now is None else now) - auth_date
    if age > max_age_seconds or age < -_CLOCK_SKEW_SECONDS:
        raise InitDataError("expired")
    user_raw = pairs.get("user")
    if not user_raw:
        raise InitDataError("missing_user")
    try:
        user = json.loads(user_raw)
    except json.JSONDecodeError as exc:
        raise InitDataError("bad_user") from exc
    telegram_id = user.get("id")
    if not isinstance(telegram_id, int):
        raise InitDataError("missing_user_id")
    username = user.get("username")
    if username is not None:
        username = str(username)
    return VerifiedWebApp(telegram_id=telegram_id, username=username)
