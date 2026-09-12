from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from urllib.parse import parse_qsl


class InitDataError(Exception):
    """Invalid or missing Telegram Mini App initData."""


@dataclass(frozen=True)
class VerifiedWebApp:
    telegram_id: int
    username: str | None


def validate_init_data(init_data: str | None, bot_token: str) -> VerifiedWebApp:
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
    try:
        valid = hmac.compare_digest(computed, received_hash)
    except ValueError as exc:
        raise InitDataError("bad_hash") from exc
    if not valid:
        raise InitDataError("bad_hash")
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
