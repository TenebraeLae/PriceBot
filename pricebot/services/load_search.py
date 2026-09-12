from __future__ import annotations

import asyncio
import statistics
import time
from pathlib import Path
from typing import Any

from httpx import ASGITransport, AsyncClient


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * q / 100
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    frac = rank - low
    return ordered[low] * (1 - frac) + ordered[high] * frac


def _summarize(latencies: list[float], statuses: list[int], n: int) -> dict[str, float | int]:
    errors_5xx = sum(1 for code in statuses if code >= 500)
    return {
        "n": n,
        "errors_5xx": errors_5xx,
        "p50_ms": round(_percentile(latencies, 50), 2),
        "p95_ms": round(_percentile(latencies, 95), 2),
        "mean_ms": round(statistics.fmean(latencies) if latencies else 0.0, 2),
        "concurrent": 1,
    }


async def _gather_hits(client: AsyncClient, headers: dict[str, str], n: int, q: str) -> dict[str, float | int]:
    async def hit() -> tuple[float, int]:
        started = time.perf_counter()
        response = await client.get("/api/v1/search", params={"q": q}, headers=headers)
        elapsed = (time.perf_counter() - started) * 1000
        return elapsed, response.status_code

    pairs = await asyncio.gather(*[hit() for _ in range(n)])
    latencies = [item[0] for item in pairs]
    statuses = [item[1] for item in pairs]
    report = _summarize(latencies, statuses, n)
    report["concurrent"] = n
    return report


async def run_search_load_async(
    app: Any,
    headers: dict[str, str],
    *,
    n: int,
    q: str = "цемент",
) -> dict[str, float | int]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await _gather_hits(client, headers, n, q)


async def run_search_load_http_async(
    base_url: str,
    headers: dict[str, str],
    *,
    n: int,
    q: str = "цемент",
) -> dict[str, float | int]:
    async with AsyncClient(base_url=base_url.rstrip("/"), timeout=60.0) as client:
        return await _gather_hits(client, headers, n, q)


def run_search_load(
    client: Any,
    headers: dict[str, str],
    *,
    n: int,
    q: str = "цемент",
) -> dict[str, float | int]:
    return asyncio.run(run_search_load_async(client.app, headers, n=n, q=q))


def write_load_report(report: dict[str, float | int], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "# Нагрузка поиска PriceBot",
                "",
                f"- N: {report['n']}",
                f"- concurrent: {report.get('concurrent', report['n'])}",
                f"- 5xx: {report['errors_5xx']}",
                f"- p50: {report['p50_ms']} ms",
                f"- p95: {report['p95_ms']} ms",
                f"- mean: {report['mean_ms']} ms",
                "",
                "Прогон: `uv run python scripts/load_search.py --n 1000` (in-process SQLite).",
                "Postgres/live: `uv run python scripts/load_search.py --n 1000 --base-url http://localhost:8080`.",
                "",
            ]
        ),
        encoding="utf-8",
    )
