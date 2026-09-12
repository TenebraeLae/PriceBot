# PriceBot

Telegram-бот и Mini App витрины по прайс-листу Excel. Закон продукта: `docs/TZ.md`. Журнал: `docs/PROGRESS.md`.

## Быстрый старт

```bash
copy .env.example .env
uv sync
uv run pytest -q
uv run ruff check pricebot tests
docker compose up -d postgres redis
```

Точки входа: `pricebot.bot.main:main`, `pricebot.web.main:app`. Поставка: `docs/ADMIN.md`. Секреты только в `.env`.
