from dataclasses import dataclass
from io import BytesIO

import qrcode
from qrcode.constants import ERROR_CORRECT_M

from pricebot.domain.errors import DomainError


@dataclass(frozen=True)
class QrImage:
    payload: str
    png_bytes: bytes


def render_qr(payload: str) -> QrImage:
    if not payload or not payload.strip():
        raise DomainError("empty_qr_payload", "Пустой контур QR не пишется")
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=8, border=2)
    qr.add_data(payload)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    png = buffer.getvalue()
    if len(png) <= 0:
        raise DomainError("empty_qr", "QR пустой")
    return QrImage(payload=payload, png_bytes=png)
