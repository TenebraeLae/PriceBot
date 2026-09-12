from pricebot.bot.texts import PHOTO_NEED_CAPTION
from pricebot.domain.catalog import CatalogProduct, product_card
from pricebot.domain.photo import is_http_photo, resolve_product_photo, safe_sku


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
