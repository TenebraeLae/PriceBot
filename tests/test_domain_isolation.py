from pathlib import Path

DOMAIN = Path(__file__).resolve().parents[1] / "pricebot" / "domain"
FORBIDDEN = ("fastapi", "aiogram", "uvicorn")


def test_domain_has_no_web_or_bot_imports() -> None:
    for path in DOMAIN.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in FORBIDDEN:
            assert f"import {name}" not in text
            assert f"from {name}" not in text
