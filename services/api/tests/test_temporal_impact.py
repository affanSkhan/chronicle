import fitz


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


def test_source_event_flags_dependent_claims_and_report(client) -> None:
    run_response = client.post(
        "/api/v1/research/runs",
        json={"question": "How does an intervention affect learning outcomes?", "mode": "forensic"},
    )
    assert run_response.status_code == 201, run_response.text
    run_id = run_response.json()["id"]

    origin = upload_pdf(client, "This original study reports the initial experiment and dataset.", "origin.pdf")
    dependent = upload_pdf(client, "This follow-up analysis reuses the original dataset.", "dependent.pdf")
    origin_id = origin["paper_id"]
    dependent_id = dependent["paper_id"]

    status_preview = client.get(f"/api/v1/sources/papers/{origin_id}/status-check")
    assert status_preview.status_code == 200, status_preview.text
    assert status_preview.json()["signals"] == []
    assert status_preview.json()["providers"]["crossref"] == "skipped_no_doi"

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

    audit_response = client.get(f"/api/v1/evidence/runs/{run_id}/audit")
    assert audit_response.status_code == 200, audit_response.text
    audit_events = audit_response.json()["events"]
    assert any(item["action"] == "claim.created" and item["actor_user_id"] for item in audit_events)
    assert any(item["action"] == "evidence_relation.created" for item in audit_events)
    review_audit = next(item for item in audit_events if item["action"] == "evidence_relation.reviewed")
    assert review_audit["previous_value"]["reviewer_status"] == "unreviewed"
    assert review_audit["new_value"]["reviewer_status"] == "accepted"
    assert review_audit["reason"] == "I reviewed the exact passage and it directly supports the statement."

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
    original_report_id = report_response.json()["id"]

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
    repeated_event = client.post(
        f"/api/v1/sources/papers/{origin_id}/events",
        json={
            "event_type": "retraction",
            "description": "Publisher metadata indicates the original study has been retracted.",
            "source_url": "https://example.org/retraction-notice",
            "verification_status": "human_verified",
        },
    )
    assert repeated_event.status_code == 201, repeated_event.text
    assert repeated_event.json()["duplicate"] is True
    assert repeated_event.json()["event"]["id"] == event_response.json()["event"]["id"]
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
    assert len(reports) == 2
    assert reports[0]["review_required"] is True
    assert reports[0]["parent_version_id"] == original_report_id
    assert reports[1]["id"] == original_report_id
    assert reports[1]["review_required"] is False
    assert "Temporal source update" in reports[0]["content_markdown"]

    passport_response = client.get(f"/api/v1/evidence/runs/{run_id}/passport?format=json")
    assert passport_response.status_code == 200, passport_response.text
    passport = passport_response.json()
    assert passport["scope"]["run_id"] == run_id
    assert any(paper["id"] == dependent_id for paper in passport["papers"])
    assert any(paper["id"] == origin_id for paper in passport["papers"])
    assert any(claim["id"] == claim_id for claim in passport["claims"])
    assert any(event["paper_id"] == origin_id for event in passport["source_events"])
    assert any(report["review_required"] for report in passport["report_versions"])
    assert any(item["action"] == "claim.flagged_by_source_event" for item in passport["audit_events"])
    assert any(item["action"] == "report_version.created_after_source_event" for item in passport["audit_events"])
    assert any(dep["relation_type"] == "same_dataset" for dep in passport["paper_dependencies"])

    markdown_passport = client.get(f"/api/v1/evidence/runs/{run_id}/passport?format=markdown")
    assert markdown_passport.status_code == 200
    assert "Chronicle Evidence Passport" in markdown_passport.text
    assert "Exact text:" in markdown_passport.text


def test_upload_rejects_non_pdf(client) -> None:
    response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("fake.pdf", b"not a PDF", "application/pdf")},
    )
    assert response.status_code == 415


def test_dependency_suggestions_do_not_auto_create_graph_edges(client) -> None:
    first = client.post(
        "/api/v1/sources/papers",
        json={"provider": "manual", "title": "One study", "abstract": "This paper uses MIMIC-IV patient records."},
    )
    second = client.post(
        "/api/v1/sources/papers",
        json={"provider": "manual", "title": "Another study", "abstract": "This paper also uses MIMIC-IV patient records."},
    )
    assert first.status_code == 201 and second.status_code == 201
    candidates = client.get("/api/v1/evidence/dependency-candidates").json()["candidates"]
    assert any({c["paper_a_id"], c["paper_b_id"]} == {first.json()["id"], second.json()["id"]} for c in candidates)
