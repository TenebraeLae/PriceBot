from decimal import Decimal
from types import SimpleNamespace

from pricebot.bot.texts import ORDERS_EMPTY, QR_CAPTION, format_orders_message
from pricebot.services.orders import format_orders_list


def test_orders_list_russian_and_qr_caption() -> None:
    empty = format_orders_list([])
    assert empty == ORDERS_EMPTY
    text = format_orders_message(
        [
            SimpleNamespace(
                number="PB-20260912-0001",
                total=Decimal("450.00"),
                status="awaiting_payment",
            ),
            SimpleNamespace(number="PB-20260912-0002", total=Decimal("80.00"), status="paid"),
        ]
    )
    assert "PB-20260912-0001 · 450.00 ₽ · ожидает оплаты" in text
    assert "оплачен" in text
    caption = QR_CAPTION.format(number="PB-20260912-0001", total="450.00")
    assert "PB-20260912-0001" in caption
    assert "450.00" in caption
    assert "К оплате" in caption
