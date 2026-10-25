"""Regression coverage for multi-hop temporal evidence-impact propagation."""

import fitz


def _make_pdf(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    content = document.tobytes()
    document.close()
    return content


def _upload_pdf(client, text: str, filename: str) -> dict:
    response = client.post(
        "/api/v1/documents/upload",
        files={"file": (filename, _make_pdf(text), "application/pdf")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _claim(client, run_id: str, statement: str) -> str:
    response = client.post(
        "/api/v1/evidence/claims",
        json={"run_id": run_id, "statement": statement},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _relate_claim_to_passage(client, claim_id: str, passage_id: str) -> None:
    response = client.post(
        f"/api/v1/evidence/claims/{claim_id}/relations",
        json={
            "passage_id": passage_id,
            "relation_type": "supports",
            "provenance_basis": "source_documented",
            "reviewer_status": "unreviewed",
            "rationale": "This passage is the stored evidence record for the claim.",
        },
    )
    assert response.status_code == 201, response.text


def _relate_claims(client, dependent_claim_id: str, source_claim_id: str) -> None:
    response = client.post(
        f"/api/v1/evidence/claims/{dependent_claim_id}/relations",
        json={
            "related_claim_id": source_claim_id,
            "relation_type": "depends_on",
            "provenance_basis": "human_reviewed",
            "reviewer_status": "accepted",
            "rationale": "The downstream claim explicitly depends on the upstream claim.",
        },
    )
    assert response.status_code == 201, response.text


def _paper_dependency(client, dependent_paper_id: str, source_paper_id: str) -> None:
    response = client.post(
        "/api/v1/evidence/paper-dependencies",
        json={
            "dependent_paper_id": dependent_paper_id,
            "depends_on_paper_id": source_paper_id,
            "relation_type": "derived_from",
            "provenance_basis": "human_reviewed",
            "rationale": "The downstream paper explicitly reuses the upstream study.",
            "confidence": 1.0,
        },
    )
    assert response.status_code == 201, response.text


def test_source_event_propagates_multi_hop_without_invalidating_unrelated_claims(client) -> None:
    run_response = client.post(
        "/api/v1/research/runs",
        json={
            "question": "How does source quality affect conclusions?",
            "mode": "forensic",
        },
    )
    assert run_response.status_code == 201, run_response.text
    run_id = run_response.json()["id"]

    origin = _upload_pdf(client, "Original study and its primary evidence.", "origin.pdf")
    middle = _upload_pdf(client, "Follow-up study derived from the original study.", "middle.pdf")
    leaf = _upload_pdf(client, "Later analysis derived from the follow-up study.", "leaf.pdf")
    unrelated = _upload_pdf(client, "An unrelated study on a different question.", "unrelated.pdf")

    origin_id = origin["paper_id"]
    middle_id = middle["paper_id"]
    leaf_id = leaf["paper_id"]
    unrelated_paper_id = unrelated["paper_id"]

    _paper_dependency(client, middle_id, origin_id)
    _paper_dependency(client, leaf_id, middle_id)

    passage_response = client.get(f"/api/v1/documents/papers/{origin_id}/passages")
    assert passage_response.status_code == 200, passage_response.text
    origin_passage_id = passage_response.json()["passages"][0]["id"]

    seed_claim = _claim(client, run_id, "The original source supports the primary conclusion.")
    middle_claim = _claim(client, run_id, "A downstream conclusion depends on the primary claim.")
    leaf_claim = _claim(client, run_id, "A later conclusion depends on the downstream conclusion.")
    unrelated_claim = _claim(client, run_id, "An unrelated conclusion has no evidence dependency.")

    _relate_claim_to_passage(client, seed_claim, origin_passage_id)
    _relate_claims(client, middle_claim, seed_claim)
    _relate_claims(client, leaf_claim, middle_claim)

    report_response = client.post(
        f"/api/v1/evidence/runs/{run_id}/reports",
        json={
            "title": "Before source event",
            "content_markdown": "The report contains conclusions derived from the original source.",
        },
    )
    assert report_response.status_code == 201, report_response.text
    original_report_id = report_response.json()["id"]

    event_response = client.post(
        f"/api/v1/sources/papers/{origin_id}/events",
        json={
            "event_type": "retraction",
            "description": "A verified source event requires reassessment of dependent conclusions.",
            "source_url": "https://example.org/retraction-notice",
            "verification_status": "human_verified",
        },
    )
    assert event_response.status_code == 201, event_response.text
    impact = event_response.json()["impact"]

    impacted_papers = set(impact["impacted_paper_ids"])
    assert {origin_id, middle_id, leaf_id} <= impacted_papers
    assert unrelated_paper_id not in impacted_papers

    affected_claim_ids = set(impact["affected_claim_ids"])
    assert {seed_claim, middle_claim, leaf_claim} <= affected_claim_ids
    assert unrelated_claim not in affected_claim_ids

    claim_rows = client.get(f"/api/v1/evidence/runs/{run_id}/claims")
    assert claim_rows.status_code == 200, claim_rows.text
    claims_by_id = {claim["id"]: claim for claim in claim_rows.json()}
    for claim_id in (seed_claim, middle_claim, leaf_claim):
        assert claims_by_id[claim_id]["review_required"] is True
        # A source event must request review, not silently declare the conclusion false.
        assert claims_by_id[claim_id]["assessment"] != "contradicted"
    assert claims_by_id[unrelated_claim]["review_required"] is False

    report_rows = client.get(f"/api/v1/evidence/runs/{run_id}/reports")
    assert report_rows.status_code == 200, report_rows.text
    reports = report_rows.json()
    assert len(reports) == 2
    latest = reports[0]
    original = next(report for report in reports if report["id"] == original_report_id)
    assert latest["review_required"] is True
    assert original["review_required"] is False
    assert latest["parent_version_id"] == original_report_id
