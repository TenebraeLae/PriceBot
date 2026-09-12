from fastapi.testclient import TestClient

from pricebot.web.main import app
from pricebot.web.metrics import reset_metrics


def test_metrics_endpoint() -> None:
    reset_metrics()
    client = TestClient(app)
    health = client.get("/health")
    assert health.status_code == 200
    response = client.get("/metrics")
    assert response.status_code == 200
    text = response.text
    assert "pricebot_up 1" in text
    assert "pricebot_http_requests_total" in text
    assert 'path="/health"' in text
    assert 'path="/metrics"' not in text
