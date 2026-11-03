from sqlalchemy import event

from app.api.evidence import _load_run_dependency_neighborhood
from app.models.entities import Paper, PaperDependency, ReportVersion, User
from conftest import TEST_ENGINE, TestingSessionLocal


def _create_run(client) -> str:
    response = client.post(
        "/api/v1/research/runs",
        json={
            "question": "How should an evidence graph load records efficiently?",
            "mode": "quick",
            "max_sources": 5,
            "execute": False,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _owned_papers(owner_id: str, prefix: str, count: int) -> list[Paper]:
    with TestingSessionLocal() as db:
        papers = [
            Paper(
                owner_user_id=owner_id,
                title=f"{prefix} paper {index}",
                authors=[],
                source_provider="manual",
            )
            for index in range(count)
        ]
        db.add_all(papers)
        db.commit()
        return papers


def test_empty_run_graph_skips_account_wide_dependency_scan(client):
    """A new run must not scan unrelated papers/dependencies in the user's library."""
    run_id = _create_run(client)
    owner_id = client.get("/api/v1/auth/me").json()["id"]

    unrelated = _owned_papers(owner_id, "unrelated", 20)
    with TestingSessionLocal() as db:
        db.add_all([
            PaperDependency(
                dependent_paper_id=unrelated[index + 1].id,
                depends_on_paper_id=unrelated[index].id,
                relation_type="derived_from",
                provenance_basis="human_reviewed",
                rationale="Unrelated library test dependency.",
            )
            for index in range(len(unrelated) - 1)
        ])
        db.commit()

    statements: list[str] = []

    def capture_sql(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.lower())

    event.listen(TEST_ENGINE, "before_cursor_execute", capture_sql)
    try:
        response = client.get(f"/api/v1/evidence/runs/{run_id}/graph")
    finally:
        event.remove(TEST_ENGINE, "before_cursor_execute", capture_sql)

    assert response.status_code == 200, response.text
    graph = response.json()
    assert graph["nodes"] == []
    assert graph["edges"] == []
    assert graph["truncated"] is False
    assert not any("from paper_dependencies" in sql for sql in statements)


def test_graph_loads_only_dependency_component_touching_selected_run(client):
    run_id = _create_run(client)
    owner_id = client.get("/api/v1/auth/me").json()["id"]
    paper_a, paper_b, paper_c, unrelated_a, unrelated_b = _owned_papers(
        owner_id, "graph", 5
    )

    with TestingSessionLocal() as db:
        db.add_all([
            PaperDependency(
                dependent_paper_id=paper_b.id,
                depends_on_paper_id=paper_a.id,
                relation_type="derived_from",
                provenance_basis="human_reviewed",
                rationale="The second paper reuses the first source.",
            ),
            PaperDependency(
                dependent_paper_id=paper_c.id,
                depends_on_paper_id=paper_b.id,
                relation_type="same_dataset",
                provenance_basis="human_reviewed",
                rationale="The third paper reuses the same dataset.",
            ),
            PaperDependency(
                dependent_paper_id=unrelated_b.id,
                depends_on_paper_id=unrelated_a.id,
                relation_type="derived_from",
                provenance_basis="human_reviewed",
                rationale="This pair is unrelated to the selected research run.",
            ),
        ])
        db.add(ReportVersion(
            run_id=run_id,
            version_number=1,
            title="Run-specific evidence",
            content_markdown="The graph should only show the selected run's sources.",
            evidence_snapshot={"paper_ids": [paper_a.id]},
        ))
        db.commit()

    response = client.get(f"/api/v1/evidence/runs/{run_id}/graph")
    assert response.status_code == 200, response.text
    graph = response.json()
    paper_node_ids = {node["id"] for node in graph["nodes"] if node["type"] == "paper"}
    assert paper_node_ids == {
        f"paper:{paper_a.id}",
        f"paper:{paper_b.id}",
        f"paper:{paper_c.id}",
    }
    dependency_edges = {
        (edge["source"], edge["target"], edge["type"])
        for edge in graph["edges"]
        if edge["type"] in {"derived_from", "same_dataset"}
    }
    assert dependency_edges == {
        (f"paper:{paper_a.id}", f"paper:{paper_b.id}", "derived_from"),
        (f"paper:{paper_b.id}", f"paper:{paper_c.id}", "same_dataset"),
    }
    assert graph["truncated"] is False


def test_dependency_neighborhood_is_owner_scoped_and_edge_bounded(monkeypatch, client):
    from app.api import evidence as evidence_api

    owner_id = client.get("/api/v1/auth/me").json()["id"]
    owner_a, owner_b, owner_c, owner_d = _owned_papers(owner_id, "bounded", 4)
    with TestingSessionLocal() as db:
        other_owner = User(
            email="other-graph-owner@example.test",
            password_hash="test-only-hash",
        )
        db.add(other_owner)
        db.flush()
        foreign_paper = Paper(
            owner_user_id=other_owner.id,
            title="Foreign owner paper",
            authors=[],
            source_provider="manual",
        )
        db.add(foreign_paper)
        db.flush()
        db.add_all([
            PaperDependency(
                dependent_paper_id=owner_b.id,
                depends_on_paper_id=owner_a.id,
                relation_type="derived_from",
                rationale="Owned edge one.",
            ),
            PaperDependency(
                dependent_paper_id=owner_c.id,
                depends_on_paper_id=owner_b.id,
                relation_type="derived_from",
                rationale="Owned edge two.",
            ),
            PaperDependency(
                dependent_paper_id=owner_d.id,
                depends_on_paper_id=owner_c.id,
                relation_type="derived_from",
                rationale="Owned edge three.",
            ),
            PaperDependency(
                dependent_paper_id=owner_a.id,
                depends_on_paper_id=foreign_paper.id,
                relation_type="derived_from",
                rationale="Must not cross the tenant boundary.",
            ),
        ])
        db.commit()
        monkeypatch.setattr(evidence_api, "MAX_GRAPH_DEPENDENCIES", 2)
        dependencies, reachable_ids, truncated = _load_run_dependency_neighborhood(
            db,
            owner_id,
            {owner_a.id},
        )

    assert len(dependencies) == 2
    assert reachable_ids == {owner_a.id, owner_b.id, owner_c.id}
    assert truncated is True
    assert all(
        edge.dependent_paper_id != owner_a.id or edge.depends_on_paper_id != foreign_paper.id
        for edge in dependencies
    )
