from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

APP = Path(__file__).resolve().parents[1] / "pricebot" / "web" / "app"
PAPER = (212, 193, 154)
INK = (27, 20, 13)
STAMP = (143, 20, 20)
RULE = (42, 70, 56)
CHALK = (239, 226, 196)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_icon(size: int) -> Image.Image:
    image = Image.new("RGB", (size, size), PAPER)
    draw = ImageDraw.Draw(image)
    margin = size // 10
    draw.rounded_rectangle(
        (margin, margin, size - margin, size - margin),
        radius=size // 12,
        outline=RULE,
        width=max(2, size // 48),
    )
    stamp = size // 3
    left = size // 2 - stamp // 2
    top = size // 5
    draw.rectangle((left, top, left + stamp, top + stamp), outline=STAMP, width=max(3, size // 36))
    mark = _font(max(18, size // 4))
    text = "№"
    box = draw.textbbox((0, 0), text, font=mark)
    tw, th = box[2] - box[0], box[3] - box[1]
    draw.text(
        (size // 2 - tw // 2, top + stamp // 2 - th // 2 - box[1] // 4),
        text,
        fill=STAMP,
        font=mark,
    )
    caption = _font(max(12, size // 8))
    label = "ПРАЙС"
    box = draw.textbbox((0, 0), label, font=caption)
    lw = box[2] - box[0]
    draw.text((size // 2 - lw // 2, top + stamp + size // 14), label, fill=INK, font=caption)
    draw.rectangle((margin * 2, size - margin * 2, size - margin * 2, size - margin * 2 + 2), fill=CHALK)
    return image


def main() -> None:
    APP.mkdir(parents=True, exist_ok=True)
    icon192 = make_icon(192)
    icon512 = make_icon(512)
    icon192.save(APP / "icon-192.png")
    icon512.save(APP / "icon-512.png")
    icon192.save(APP / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    manifest = {
        "name": "Прайс",
        "short_name": "Прайс",
        "start_url": "./",
        "display": "standalone",
        "background_color": "#d4c19a",
        "theme_color": "#d4c19a",
        "icons": [
            {"src": "./icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "./icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    }
    (APP / "manifest.webmanifest").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(APP / "favicon.ico")
    print(APP / "icon-192.png")
    print(APP / "icon-512.png")
    print(APP / "manifest.webmanifest")


if __name__ == "__main__":
    main()
