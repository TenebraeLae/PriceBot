import pytest

from pricebot.web.auth import InitDataError, validate_init_data
from tests.conftest import make_init_data

TOKEN = "1:test-token"


def test_valid_init_data_returns_user_id() -> None:
    raw = make_init_data(TOKEN, 555, "buyer")
    verified = validate_init_data(raw, TOKEN)
    assert verified.telegram_id == 555
    assert verified.username == "buyer"


def test_missing_init_data_rejected() -> None:
    with pytest.raises(InitDataError):
        validate_init_data("", TOKEN)


def test_tampered_user_rejected() -> None:
    raw = make_init_data(TOKEN, 555).replace("555", "999")
    with pytest.raises(InitDataError):
        validate_init_data(raw, TOKEN)


def test_foreign_bot_token_rejected() -> None:
    raw = make_init_data(TOKEN, 555)
    with pytest.raises(InitDataError):
        validate_init_data(raw, "9:other-token")


def test_expired_init_data_rejected() -> None:
    raw = make_init_data(TOKEN, 555, auth_date=1_700_000_000)
    with pytest.raises(InitDataError, match="expired"):
        validate_init_data(raw, TOKEN, now=1_700_000_000 + 86_401)


def test_init_data_within_max_age_accepted() -> None:
    raw = make_init_data(TOKEN, 555, auth_date=1_700_000_000)
    verified = validate_init_data(raw, TOKEN, now=1_700_000_000 + 60)
    assert verified.telegram_id == 555


def test_missing_auth_date_rejected() -> None:
    import hashlib
    import hmac
    import json
    from urllib.parse import urlencode

    user = json.dumps({"id": 555, "username": "buyer"}, separators=(",", ":"))
    fields = {"query_id": "AAEtest", "user": user}
    check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TOKEN.encode("utf-8"), hashlib.sha256).digest()
    digest = hmac.new(secret, check.encode("utf-8"), hashlib.sha256).hexdigest()
    raw = urlencode({**fields, "hash": digest})
    with pytest.raises(InitDataError, match="bad_auth_date"):
        validate_init_data(raw, TOKEN)
