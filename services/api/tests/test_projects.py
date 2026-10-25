def test_project_can_be_renamed_archived_and_restored(client) -> None:
    created = client.post("/api/v1/projects", json={
        "title": "Chronicle acceptance workspace",
        "research_question": "How can evidence histories remain inspectable?",
    })
    assert created.status_code == 201, created.text
    project = created.json()
    assert project["archived_at"] is None

    renamed = client.patch(f"/api/v1/projects/{project['id']}", json={
        "title": "Temporal evidence workspace",
        "research_question": "How should source updates affect stored claims?",
    })
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["title"] == "Temporal evidence workspace"
    assert renamed.json()["research_question"] == "How should source updates affect stored claims?"

    archived = client.patch(f"/api/v1/projects/{project['id']}", json={"archived": True})
    assert archived.status_code == 200, archived.text
    assert archived.json()["archived_at"] is not None
    assert client.get("/api/v1/projects").json() == []
    assert len(client.get("/api/v1/projects?include_archived=true").json()) == 1

    rejected_run = client.post("/api/v1/research/runs", json={
        "project_id": project["id"],
        "question": "Can an archived workspace run a new research task?",
        "mode": "deep",
        "execute": False,
    })
    assert rejected_run.status_code == 409, rejected_run.text

    restored = client.patch(f"/api/v1/projects/{project['id']}", json={"archived": False})
    assert restored.status_code == 200, restored.text
    assert restored.json()["archived_at"] is None
    assert [item["id"] for item in client.get("/api/v1/projects").json()] == [project["id"]]


def test_project_updates_are_owner_scoped(client) -> None:
    created = client.post("/api/v1/projects", json={
        "title": "Private workspace",
        "research_question": "How should private research be isolated?",
    })
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]
    original_authorization = client.headers["Authorization"]
    second_account = client.post("/api/v1/auth/register", json={
        "email": "different-owner@example.test",
        "password": "another-test-password-12",
    })
    assert second_account.status_code == 201, second_account.text
    client.headers["Authorization"] = f"Bearer {second_account.json()['access_token']}"
    assert client.get(f"/api/v1/projects/{project_id}").status_code == 404
    assert client.patch(f"/api/v1/projects/{project_id}", json={"title": "Hijacked title"}).status_code == 404
    client.headers["Authorization"] = original_authorization


def test_project_update_rejects_empty_patch(client) -> None:
    created = client.post("/api/v1/projects", json={
        "title": "Empty patch workspace",
        "research_question": "How should an empty update be handled?",
    })
    assert created.status_code == 201, created.text
    response = client.patch(f"/api/v1/projects/{created.json()['id']}", json={})
    assert response.status_code == 422, response.text
