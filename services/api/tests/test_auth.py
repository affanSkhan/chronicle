from fastapi.testclient import TestClient

from app.main import app


def test_authenticated_user_can_login_and_read_profile(client) -> None:
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "fixture-user@example.test", "password": "test-password-at-least-12"},
    )
    assert login.status_code == 200, login.text
    body = login.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == "fixture-user@example.test"
    assert body["access_token"]

    with TestClient(app, headers={"Authorization": f"Bearer {body['access_token']}"}) as authenticated_client:
        me = authenticated_client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["id"] == body["user"]["id"]


def test_private_api_rejects_anonymous_requests() -> None:
    with TestClient(app) as anonymous_client:
        response = anonymous_client.get("/api/v1/research/runs")
        assert response.status_code == 401


def test_runs_are_isolated_between_two_users(client) -> None:
    created = client.post(
        "/api/v1/research/runs",
        json={"question": "How does evidence provenance affect scientific synthesis?", "mode": "academic"},
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]

    second_register = client.post(
        "/api/v1/auth/register",
        json={"email": "second-user@example.test", "password": "second-test-password-123"},
    )
    assert second_register.status_code == 201, second_register.text
    second_token = second_register.json()["access_token"]

    with TestClient(app, headers={"Authorization": f"Bearer {second_token}"}) as second_client:
        other_runs = second_client.get("/api/v1/research/runs")
        private_run = second_client.get(f"/api/v1/research/runs/{run_id}")
        private_claims = second_client.get(f"/api/v1/evidence/runs/{run_id}/claims")

    assert other_runs.status_code == 200
    assert other_runs.json() == []
    assert private_run.status_code == 404
    assert private_claims.status_code == 404


def test_registration_validates_password_and_duplicate_email(client) -> None:
    weak_password = client.post(
        "/api/v1/auth/register",
        json={"email": "weak@example.test", "password": "short"},
    )
    assert weak_password.status_code == 422

    duplicate = client.post(
        "/api/v1/auth/register",
        json={"email": "fixture-user@example.test", "password": "another-password-123"},
    )
    assert duplicate.status_code == 409
