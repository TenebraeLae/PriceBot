from pricebot.domain.catalog import CatalogProduct, product_card
from pricebot.domain.photo import is_http_photo, resolve_product_photo


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
