from fastapi.testclient import TestClient

from nebulai.main import app


def test_health() -> None:
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_provider_status() -> None:
    client = TestClient(app)
    response = client.get("/api/providers/status")

    assert response.status_code == 200
    payload = response.json()
    assert "overall" in payload
    assert "embedding" in payload["providers"]
    assert "llm" in payload["providers"]
    assert "rerank" in payload["providers"]
