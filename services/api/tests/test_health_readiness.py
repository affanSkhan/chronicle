from sqlalchemy.exc import SQLAlchemyError

from app.core.database import get_db
from app.main import app


def test_readiness_reports_database_dependency(client) -> None:
    response = client.get("/api/v1/ready")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ready"
    assert body["dependencies"] == {"database": "ok"}


def test_readiness_returns_safe_error_when_database_is_unavailable(client) -> None:
    class BrokenSession:
        def execute(self, _statement):
            raise SQLAlchemyError("private connection details must not leak")

    app.dependency_overrides[get_db] = lambda: BrokenSession()
    try:
        response = client.get("/api/v1/ready")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    assert response.json()["detail"] == "Database is unavailable."
    assert "private connection details" not in response.text
