import pytest

from pricebot.domain.errors import DomainError
from pricebot.domain.qr import render_qr


def test_qr_bytes_and_payload() -> None:
    image = render_qr("https://pay.local/fake-PB-1")
    assert image.payload == "https://pay.local/fake-PB-1"
    assert len(image.png_bytes) > 0
    assert image.png_bytes[:8] == b"\x89PNG\r\n\x1a\n"


def test_empty_payload_rejected() -> None:
    with pytest.raises(DomainError) as err:
        render_qr("  ")
    assert err.value.code == "empty_qr_payload"
