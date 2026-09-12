from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse


def safe_sku(raw: str | None) -> str | None:
    text = (raw or "").strip()
    if not text or len(text) > 64:
        return None
    if any(char in text for char in ("/", "\\", "\0")) or ".." in text:
        return None
    if text.startswith(".") or text.endswith("."):
        return None
    return text


def resolve_product_photo(photo_url: str | None) -> str | None:
    if photo_url is None:
        return None
    text = str(photo_url).strip()
    return text or None


def is_http_photo(photo_url: str | None) -> bool:
    raw = resolve_product_photo(photo_url)
    if raw is None:
        return False
    parsed = urlparse(raw)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def local_media_path(photo_url: str, media_dir: str) -> Path | None:
    raw = resolve_product_photo(photo_url)
    if raw is None:
        return None
    lowered = raw.casefold()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return None
    relative = raw.lstrip("/").removeprefix("media/")
    target = (Path(media_dir) / relative).resolve()
    root = Path(media_dir).resolve()
    if root not in target.parents and target != root:
        return None
    if not target.is_file():
        return None
    return target
