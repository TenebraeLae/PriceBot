import pytest

from pricebot.bot.texts import PHOTO_NEED_CAPTION
from pricebot.domain.catalog import CatalogProduct, product_card
from pricebot.domain.errors import DomainError
from pricebot.domain.photo import (
    MAX_PRODUCT_PHOTO_BYTES,
    is_http_photo,
    resolve_product_photo,
    safe_sku,
    validate_product_photo,
)


def test_photo_helper_url_vs_empty() -> None:
    assert resolve_product_photo(None) is None
    assert resolve_product_photo("") is None
    assert resolve_product_photo("   ") is None
    url = "https://cdn.example/p.jpg"
    assert resolve_product_photo(url) == url
    assert is_http_photo(url) is True
    assert is_http_photo("") is False
    assert resolve_product_photo("img/bag.jpg") == "img/bag.jpg"
    card = product_card(CatalogProduct(sku="X", name="Товар", photo_url="  "))
    assert card["photo_url"] is None


def test_safe_sku_and_photo_need_caption() -> None:
    assert safe_sku("CEM-M500") == "CEM-M500"
    assert safe_sku("../etc") is None
    assert safe_sku("a/b") is None
    assert safe_sku("") is None
    assert PHOTO_NEED_CAPTION
    assert "артикул" in PHOTO_NEED_CAPTION.casefold() or "подпис" in PHOTO_NEED_CAPTION.casefold()


def test_validate_product_photo_accepts_jpeg() -> None:
    validate_product_photo(b"\xff\xd8\xff" + b"jpeg-body")


def test_validate_product_photo_rejects_non_jpeg() -> None:
    with pytest.raises(DomainError) as exc:
        validate_product_photo(b"\x89PNG\r\n")
    assert exc.value.code == "photo_bad_type"


def test_validate_product_photo_rejects_oversized() -> None:
    payload = b"\xff\xd8\xff" + b"x" * MAX_PRODUCT_PHOTO_BYTES
    with pytest.raises(DomainError) as exc:
        validate_product_photo(payload)
    assert exc.value.code == "photo_too_large"
