from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root_returns_service_status() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["name"] == "Chronicle API"
    assert response.json()["status"] == "ok"


def test_health_contract() -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "Chronicle API"
    assert payload["version"]
