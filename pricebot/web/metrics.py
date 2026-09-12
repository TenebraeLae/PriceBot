from __future__ import annotations

from collections import Counter

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_REQUESTS: Counter[tuple[str, int]] = Counter()


def reset_metrics() -> None:
    _REQUESTS.clear()


def record_request(path: str, status_code: int) -> None:
    _REQUESTS[(path, status_code)] += 1


def render_metrics() -> str:
    lines = [
        "# TYPE pricebot_up gauge",
        "pricebot_up 1",
        "# TYPE pricebot_http_requests_total counter",
    ]
    for (path, status), count in sorted(_REQUESTS.items()):
        safe = path.replace("\\", "").replace('"', "")
        lines.append(
            f'pricebot_http_requests_total{{path="{safe}",status="{status}"}} {count}'
        )
    return "\n".join(lines) + "\n"


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        if request.url.path != "/metrics":
            record_request(request.url.path, response.status_code)
        return response


def mount_metrics(app: FastAPI) -> None:
    app.add_middleware(MetricsMiddleware)

    @app.get("/metrics")
    async def metrics() -> PlainTextResponse:
        return PlainTextResponse(render_metrics(), media_type="text/plain; version=0.0.4")
