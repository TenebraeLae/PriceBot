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
