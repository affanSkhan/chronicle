import fitz

from conftest import TestingSessionLocal


def make_pdf(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data


def upload_pdf(client, text: str, filename: str) -> dict:
    response = client.post(
        "/api/v1/documents/upload",
        files={"file": (filename, make_pdf(text), "application/pdf")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_contextual_claim_comparison_uses_study_context_and_persists_review_edge(monkeypatch, client):
    import app.api.evidence as evidence_routes
    from app.models.entities import Study

    run = client.post(
        "/api/v1/research/runs",
        json={"question": "How do intervention effects vary by population?", "mode": "academic"},
    )
    assert run.status_code == 201, run.text
    run_id = run.json()["id"]

    pdf_a = upload_pdf(
        client,
        "A randomized study of 120 adult patients found improved symptom scores after six weeks.",
        "adult-study.pdf",
    )
    pdf_b = upload_pdf(
        client,
        "An observational study of 40 pediatric patients found no clear change in the school attendance outcome.",
        "pediatric-study.pdf",
    )
    passages_a_response = client.get(f"/api/v1/documents/papers/{pdf_a['paper_id']}/passages")
    passages_b_response = client.get(f"/api/v1/documents/papers/{pdf_b['paper_id']}/passages")
    assert passages_a_response.status_code == 200, passages_a_response.text
    assert passages_b_response.status_code == 200, passages_b_response.text
    passages_a = passages_a_response.json()["passages"]
    passages_b = passages_b_response.json()["passages"]
    assert passages_a and passages_b
    passage_a_id, passage_b_id = passages_a[0]["id"], passages_b[0]["id"]

    with TestingSessionLocal() as db:
        db.add(Study(
            paper_id=pdf_a["paper_id"],
            source_passage_id=passage_a_id,
            study_type="randomized controlled trial",
            population="120 adult patients",
            method="randomized allocation, six-week follow-up",
            intervention="clinical intervention",
            outcomes=["symptom score"],
            limitations=["single site"],
            extraction_basis="source_documented",
        ))
        db.add(Study(
            paper_id=pdf_b["paper_id"],
            source_passage_id=passage_b_id,
            study_type="observational study",
            population="40 pediatric patients",
            method="observational comparison",
            intervention="clinical intervention",
            outcomes=["school attendance"],
            limitations=["small sample"],
            extraction_basis="source_documented",
        ))
        db.commit()

    claim_a = client.post(
        "/api/v1/evidence/claims",
        json={
            "run_id": run_id,
            "statement": "The intervention improves symptom scores in adult patients.",
            "scope": {"population": "adult patients", "outcome": "symptom score"},
        },
    )
    claim_b = client.post(
        "/api/v1/evidence/claims",
        json={
            "run_id": run_id,
            "statement": "The intervention has no clear effect on school attendance in pediatric patients.",
            "scope": {"population": "pediatric patients", "outcome": "school attendance"},
        },
    )
    assert claim_a.status_code == 201, claim_a.text
    assert claim_b.status_code == 201, claim_b.text

    for claim_id, passage_id in (
        (claim_a.json()["id"], passage_a_id),
        (claim_b.json()["id"], passage_b_id),
    ):
        edge = client.post(
            f"/api/v1/evidence/claims/{claim_id}/relations",
            json={
                "passage_id": passage_id,
                "relation_type": "supports",
                "provenance_basis": "source_documented",
                "reviewer_status": "unreviewed",
                "rationale": "Exact passage selected from the uploaded paper.",
            },
        )
        assert edge.status_code == 201, edge.text

    async def fake_compare(**kwargs):
        assert kwargs["claim_a"]["id"] == claim_a.json()["id"]
        assert kwargs["claim_b"]["id"] == claim_b.json()["id"]
        assert kwargs["passages_a"][0]["study_context"]["population"] == "120 adult patients"
        assert kwargs["passages_a"][0]["study_context"]["method"].startswith("randomized")
        assert kwargs["passages_b"][0]["study_context"]["population"] == "40 pediatric patients"
        assert kwargs["passages_b"][0]["study_context"]["outcomes"] == ["school attendance"]
        return {
            "relation_type": "not_comparable",
            "rationale": "The claims describe different study populations and outcome definitions.",
            "comparability_note": "The adult symptom-score trial is not directly comparable to the pediatric attendance study.",
            "population_comparison": "Adults versus pediatric patients; populations differ materially.",
            "method_comparison": "Randomized trial versus observational comparison.",
            "outcome_comparison": "Symptom score versus school attendance; outcomes are not interchangeable.",
            "evidence_passage_ids": [passage_a_id, passage_b_id],
            "uncertainty_notes": ["Both records are passage excerpts; inspect the full methods and outcome definitions."],
            "human_review_required": True,
            "provenance_basis": "model_inferred",
            "model": "test-model",
        }

    monkeypatch.setattr(evidence_routes, "compare_claims_with_context", fake_compare)
    response = client.post(
        f"/api/v1/evidence/claims/{claim_a.json()['id']}/compare/{claim_b.json()['id']}"
    )
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["relation_type"] == "not_comparable"
    assert result["reviewer_status"] == "unreviewed"
    assert result["human_review_required"] is True
    assert set(result["evidence_passage_ids"]) == {passage_a_id, passage_b_id}

    relations = client.get(f"/api/v1/evidence/claims/{claim_a.json()['id']}/relations")
    assert relations.status_code == 200, relations.text
    saved = next(item for item in relations.json() if item["id"] == result["relation_id"])
    assert saved["related_claim_id"] == claim_b.json()["id"]
    assert saved["relation_type"] == "not_comparable"
    assert saved["reviewer_status"] == "unreviewed"

    with TestingSessionLocal() as db:
        from app.models.entities import EvidenceRelation
        from sqlalchemy import select

        saved_edge = db.scalar(select(EvidenceRelation).where(EvidenceRelation.id == result["relation_id"]))
        assert saved_edge is not None
        assert saved_edge.metadata_snapshot["contextual_comparison"]["evidence_passage_ids"] == [passage_a_id, passage_b_id]

    audit = client.get(f"/api/v1/evidence/runs/{run_id}/audit")
    assert audit.status_code == 200, audit.text
    assert any(
        event["action"] == "evidence_relation.contextual_comparison_completed"
        and event["target_entity_id"] == result["relation_id"]
        for event in audit.json()["events"]
    )


def test_contextual_comparison_requires_two_claims_with_evidence(client):
    run = client.post(
        "/api/v1/research/runs",
        json={"question": "How do interventions affect outcomes in different studies?", "mode": "academic"},
    )
    assert run.status_code == 201, run.text
    claim_a = client.post(
        "/api/v1/evidence/claims",
        json={"run_id": run.json()["id"], "statement": "The first claim is supported by an initial study."},
    )
    claim_b = client.post(
        "/api/v1/evidence/claims",
        json={"run_id": run.json()["id"], "statement": "The second claim is supported by another study."},
    )
    assert claim_a.status_code == 201, claim_a.text
    assert claim_b.status_code == 201, claim_b.text
    response = client.post(
        f"/api/v1/evidence/claims/{claim_a.json()['id']}/compare/{claim_b.json()['id']}"
    )
    assert response.status_code == 422
    assert "evidence passage" in response.json()["detail"].lower()


def test_contextual_comparison_rejects_cross_run_claims(client):
    run_a = client.post(
        "/api/v1/research/runs",
        json={"question": "How does intervention A affect outcome X?", "mode": "academic"},
    )
    run_b = client.post(
        "/api/v1/research/runs",
        json={"question": "How does intervention B affect outcome Y?", "mode": "academic"},
    )
    claim_a = client.post(
        "/api/v1/evidence/claims",
        json={"run_id": run_a.json()["id"], "statement": "The intervention is associated with outcome X."},
    )
    claim_b = client.post(
        "/api/v1/evidence/claims",
        json={"run_id": run_b.json()["id"], "statement": "The intervention is associated with outcome Y."},
    )
    assert claim_a.status_code == 201, claim_a.text
    assert claim_b.status_code == 201, claim_b.text
    response = client.post(
        f"/api/v1/evidence/claims/{claim_a.json()['id']}/compare/{claim_b.json()['id']}"
    )
    assert response.status_code == 422
    assert "same research run" in response.json()["detail"]
