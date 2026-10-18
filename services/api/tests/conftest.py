import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app import models  # noqa: F401 - import mapped entities


TEST_ENGINE = create_engine(
    "sqlite+pysqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=TEST_ENGINE, autoflush=False, autocommit=False, expire_on_commit=False)


@pytest.fixture(autouse=True)
def isolated_database():
    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)
    Base.metadata.drop_all(bind=TEST_ENGINE)


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        response = test_client.post(
            "/api/v1/auth/register",
            json={"email": "fixture-user@example.test", "password": "test-password-at-least-12"},
        )
        assert response.status_code == 201, response.text
        test_client.headers.update({"Authorization": f"Bearer {response.json()['access_token']}"})
        yield test_client
