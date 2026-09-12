from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from pricebot.db.session import create_schema, make_engine, make_session_factory
from pricebot.services.load_search import (
    run_search_load,
    run_search_load_http_async,
    write_load_report,
)
from pricebot.web.deps import get_session, get_settings_dep
from pricebot.web.main import app
from tests.conftest import init_data_headers, make_test_settings
from tests.test_miniapp_api import _cleanup, _import_catalog


def main() -> None:
    parser = argparse.ArgumentParser(description="Нагрузка GET /api/v1/search")
    parser.add_argument("--n", type=int, default=100, help="Число запросов (1000 — полный прогон)")
    parser.add_argument("--q", default="цемент")
    parser.add_argument(
        "--base-url",
        default="",
        help="Живой API (Postgres), например http://localhost:8080",
    )
    args = parser.parse_args()

    if args.base_url:
        from pricebot.config import get_settings

        settings = get_settings()
        headers = init_data_headers(settings, 555)
        report = asyncio.run(
            run_search_load_http_async(args.base_url, headers, n=args.n, q=args.q)
        )
        write_load_report(report, ROOT / "docs" / "LOAD.md")
        print(
            f"n={report['n']} 5xx={report['errors_5xx']} "
            f"p50={report['p50_ms']}ms p95={report['p95_ms']}ms"
        )
        if int(report["errors_5xx"]) > 0:
            raise SystemExit(1)
        return

    tmp = Path(tempfile.mkdtemp(prefix="pricebot-load-"))
    settings = make_test_settings(tmp)
    engine = make_engine(settings.database_url)
    asyncio.run(create_schema(engine))
    factory = make_session_factory(engine)

    async def override_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_settings_dep] = lambda: settings
    app.dependency_overrides[get_session] = override_session
    client = TestClient(app)
    try:
        _import_catalog(
            client,
            tmp,
            [["CEM-M500", "Цемент М500", "450.00", 12, "Сухие смеси", "", 10]],
        )
        headers = init_data_headers(settings, 555)
        report = run_search_load(client, headers, n=args.n, q=args.q)
        write_load_report(report, ROOT / "docs" / "LOAD.md")
        print(
            f"n={report['n']} 5xx={report['errors_5xx']} "
            f"p50={report['p50_ms']}ms p95={report['p95_ms']}ms"
        )
        if int(report["errors_5xx"]) > 0:
            raise SystemExit(1)
    finally:
        _cleanup(engine)


if __name__ == "__main__":
    main()
