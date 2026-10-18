def test_create_and_get_demo_run(client) -> None:
    created = client.post(
        "/api/v1/research/runs",
        json={"question": "What are the limits of scientific RAG?", "mode": "deep", "max_sources": 8},
    )
    assert created.status_code == 201
    run = created.json()
    assert run["question"] == "What are the limits of scientific RAG?"
    assert run["status"] == "queued"
    assert run["demo"] is True

    fetched = client.get(f"/api/v1/research/runs/{run['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == run["id"]


def test_create_run_rejects_too_short_question(client) -> None:
    response = client.post("/api/v1/research/runs", json={"question": "short"})
    assert response.status_code == 422


def test_unknown_run_is_404(client) -> None:
    response = client.get("/api/v1/research/runs/not-a-real-id")
    assert response.status_code == 404
