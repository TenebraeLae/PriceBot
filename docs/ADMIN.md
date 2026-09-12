# Админка и поставка PriceBot

Секреты только в `.env` (см. `.env.example`). Не коммитить.

## Docker Compose

```bash
copy .env.example .env
docker compose up --build
```

Сервисы: `postgres`, `redis`, `api` (`:8080`), `bot`. Рестарт контейнеров не теряет том Postgres.

- Локально: `BOT_MODE=polling`.
- Прод: `BOT_MODE=webhook`, `PUBLIC_BASE_URL=https://ваш-домен`, секрет Telegram ≠ секрет платёжки.

Webhook Telegram: `POST /telegram/webhook`, заголовок `X-Telegram-Bot-Api-Secret-Token`.

## Оплата ЮKassa

По умолчанию `PAYMENT_PROVIDER=fake` (HMAC, тесты). Для demo/боевого магазина в `.env`:

```
PAYMENT_PROVIDER=yookassa
YOOKASSA_SHOP_ID=
YOOKASSA_SECRET_KEY=
# пусто → {PUBLIC_BASE_URL}/app/
YOOKASSA_RETURN_URL=
# пусто → официальные IP ЮKassa; * — без проверки IP (только локально)
YOOKASSA_TRUSTED_IPS=
```

Ключи — из личного кабинета ЮKassa (test shop для песочницы). Не коммитить. Webhook: `POST {PUBLIC_BASE_URL}/api/v1/payments/webhook`. HMAC нет: проверка IP + повторный GET платежа. Demo-магазин: карты/кошелёк на `confirmation_url`; СБП QR только на боевом магазине.

`GET /metrics` — текстовые счётчики запросов (`pricebot_up`, `pricebot_http_requests_total`).

## VPS (Ubuntu 22.04/24.04)

Профиль: 2+ vCPU / 4 ГБ RAM / NVMe.

1. Установить Docker Engine + Compose plugin.
2. Клонировать репозиторий, скопировать `.env.example` → `.env`, заполнить `BOT_TOKEN`, `ADMIN_IDS`, секреты.
3. `docker compose up -d --build`.
4. Автозапуск: у сервисов `restart: unless-stopped`. После ребута Compose поднимает стек (`sudo systemctl enable docker`). Юнит: `deploy/pricebot.service` → `/etc/systemd/system/pricebot.service`, затем `sudo systemctl enable --now pricebot`.
5. Проброс 8080 (или nginx/caddy на 443 → api:8080), HTTPS для Mini App и webhook.
6. Nightly бэкап (cron, от root или пользователя с docker):

```
15 3 * * * docker compose -f /opt/pricebot/docker-compose.yml exec -T api python scripts/backup.py
```

Файлы: `data/backups/pricebot-YYYYMMDDTHHMMSS.sql`, ротация `BACKUP_RETENTION_DAYS` (по умолчанию 7).

## Админ API (`X-Telegram-Id` ∈ `ADMIN_IDS`, иначе 403)

- `POST /api/v1/admin/import` — Excel.
- `GET /api/v1/admin/orders?number=&telegram_id=&sku=&status=`
- `POST /api/v1/admin/orders/{number}/status` — `{status}`: awaiting_payment→cancelled, paid→processing, processing→done, любой кроме done→error. `paid` только платёжный модуль.
- `GET /api/v1/admin/users`
- `POST /api/v1/admin/users/{telegram_id}/block` / `unblock`
- `POST /api/v1/admin/promos` — code, kind percent|fixed, value, starts_at, ends_at, max_uses, active
- `POST /api/v1/admin/promos/{code}/disable`
- `GET /api/v1/admin/tickets?status=open|all`
- `POST /api/v1/admin/tickets/{ticket}/reply` — `{text}`
- `GET /api/v1/admin/catalog.xlsx`

Пользователь: `POST /api/v1/tickets` `{text}` (initData). В боте: «Поддержка» → следующее сообщение создаёт обращение.

## Нагрузка

```bash
uv run python scripts/load_search.py
uv run python scripts/load_search.py --n 1000
# живой API + Postgres (docker compose, :8080)
uv run python scripts/load_search.py --n 1000 --base-url http://localhost:8080
```

Отчёт p50/p95: `docs/LOAD.md`.
