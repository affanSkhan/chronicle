from fastapi.testclient import TestClient
import fitz

from app.main import app

client = TestClient(app)


def make_pdf(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data


def upload_pdf(text: str, filename: str) -> dict:
    response = client.post(
        "/api/v1/documents/upload",
        files={"file": (filename, make_pdf(text), "application/pdf")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_source_event_flags_dependent_claims_and_report() -> None:
    run_response = client.post(
        "/api/v1/research/runs",
        json={"question": "How does an intervention affect learning outcomes?", "mode": "forensic"},
    )
    assert run_response.status_code == 201, run_response.text
    run_id = run_response.json()["id"]

    origin = upload_pdf("This original study reports the initial experiment and dataset.", "origin.pdf")
    dependent = upload_pdf("This follow-up analysis reuses the original dataset.", "dependent.pdf")
    origin_id = origin["paper_id"]
    dependent_id = dependent["paper_id"]

    passage_response = client.get(f"/api/v1/documents/papers/{dependent_id}/passages")
    assert passage_response.status_code == 200, passage_response.text
    passage_id = passage_response.json()["passages"][0]["id"]

    claim_response = client.post(
        "/api/v1/evidence/claims",
        json={"run_id": run_id, "statement": "The intervention improves the measured outcome."},
    )
    assert claim_response.status_code == 201, claim_response.text
    claim_id = claim_response.json()["id"]

    relation_response = client.post(
        f"/api/v1/evidence/claims/{claim_id}/relations",
        json={
            "passage_id": passage_id,
            "relation_type": "supports",
            "provenance_basis": "model_inferred",
            "confidence": 0.9,
            "reviewer_status": "unreviewed",
            "rationale": "The passage directly reports the outcome.",
        },
    )
    assert relation_response.status_code == 201, relation_response.text
    relation_id = relation_response.json()["id"]
    review_response = client.patch(
        f"/api/v1/evidence/relations/{relation_id}/review",
        json={"reviewer_status": "accepted", "reviewer_notes": "I reviewed the exact passage and it directly supports the statement."},
    )
    assert review_response.status_code == 200, review_response.text
    assert review_response.json()["reviewer_status"] == "accepted"
    assert review_response.json()["provenance_basis"] == "human_reviewed"

    dependency_response = client.post(
        "/api/v1/evidence/paper-dependencies",
        json={
            "dependent_paper_id": dependent_id,
            "depends_on_paper_id": origin_id,
            "relation_type": "same_dataset",
            "provenance_basis": "human_reviewed",
            "rationale": "Both papers explicitly describe reuse of the same dataset.",
            "confidence": 0.9,
        },
    )
    assert dependency_response.status_code == 201, dependency_response.text

    graph_response = client.get(f"/api/v1/evidence/runs/{run_id}/graph")
    assert graph_response.status_code == 200, graph_response.text
    graph = graph_response.json()
    assert any(node["id"] == f"paper:{origin_id}" for node in graph["nodes"])
    assert any(
        edge["source"] == f"paper:{origin_id}"
        and edge["target"] == f"paper:{dependent_id}"
        and edge["type"] == "same_dataset"
        for edge in graph["edges"]
    )
    assert any(
        edge["source"] == f"passage:{passage_id}"
        and edge["target"] == f"claim:{claim_id}"
        and edge["type"] == "supports"
        for edge in graph["edges"]
    )

    report_response = client.post(
        f"/api/v1/evidence/runs/{run_id}/reports",
        json={"title": "Initial report", "content_markdown": "The report concludes that the intervention may help."},
    )
    assert report_response.status_code == 201, report_response.text

    event_response = client.post(
        f"/api/v1/sources/papers/{origin_id}/events",
        json={
            "event_type": "retraction",
            "description": "Publisher metadata indicates the original study has been retracted.",
            "source_url": "https://example.org/retraction-notice",
            "verification_status": "human_verified",
        },
    )
    assert event_response.status_code == 201, event_response.text
    impact = event_response.json()["impact"]

    assert origin_id in impact["impacted_paper_ids"]
    assert dependent_id in impact["impacted_paper_ids"]
    assert claim_id in impact["affected_claim_ids"]
    assert impact["claims_flagged_for_review"] >= 1
    assert impact["report_versions_flagged_for_review"] == 1
    assert event_response.json()["event"]["metadata_snapshot"]["impact_summary"]["claims_flagged_for_review"] >= 1

    timeline_response = client.get("/api/v1/sources/events")
    assert timeline_response.status_code == 200, timeline_response.text
    timeline = timeline_response.json()
    assert timeline["count"] == 1
    assert timeline["events"][0]["paper_id"] == origin_id
    assert timeline["events"][0]["metadata_snapshot"]["impact_summary"]["report_versions_flagged_for_review"] == 1

    claims = client.get(f"/api/v1/evidence/runs/{run_id}/claims").json()
    assert next(c for c in claims if c["id"] == claim_id)["review_required"] is True
    reports = client.get(f"/api/v1/evidence/runs/{run_id}/reports").json()
    assert reports[0]["review_required"] is True


def test_upload_rejects_non_pdf() -> None:
    response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("fake.pdf", b"not a PDF", "application/pdf")},
    )
    assert response.status_code == 415
