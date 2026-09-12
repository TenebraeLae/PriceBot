# Нагрузка поиска PriceBot

- N: 1000
- concurrent: 1000
- 5xx: 0
- p50: 27726.38 ms
- p95: 30213.27 ms
- mean: 26524.06 ms

Стенд: живой uvicorn + PostgreSQL 16 + Redis (`docker compose up -d postgres redis`), 1000 одновременных GET `/api/v1/search?q=цемент`. Excel на поиск не открывается.

p50/p95 высокие из‑за 1000 задач на одном процессе API (очередь), не из‑за 5xx. Повтор: `uv run python scripts/load_search.py --n 1000 --base-url http://127.0.0.1:8080`.
