from conftest import TestingSessionLocal


def _import_paper(client, title: str, abstract: str) -> dict:
    response = client.post(
        "/api/v1/sources/papers",
        json={"provider": "manual", "title": title, "abstract": abstract, "authors": ["Test Author"]},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_dataset_dependency_candidates_are_suggestions_until_confirmed(client) -> None:
    paper_a = _import_paper(client, "Evaluation on a clinical dataset", "The model was evaluated using the MIMIC-IV critical care dataset.")
    paper_b = _import_paper(client, "A second clinical study", "This analysis reused records from MIMIC-IV to evaluate outcomes.")

    response = client.get("/api/v1/evidence/dependency-candidates")
    assert response.status_code == 200, response.text
    payload = response.json()
    candidate = next(item for item in payload["candidates"] if {item["paper_a_id"], item["paper_b_id"]} == {paper_a["id"], paper_b["id"]})
    assert candidate["relation_type"] == "same_dataset"
    assert candidate["provenance_basis"] == "metadata_inferred"
    assert "MIMIC-IV" in candidate["signals"][0]
    assert "must be verified" in candidate["rationale"]

    # Merely inspecting suggestions must not persist a graph relationship.
    with TestingSessionLocal() as db:
        from app.models.entities import PaperDependency
        assert db.query(PaperDependency).count() == 0


def test_confirmed_shared_dataset_link_flags_both_directions_for_review(client) -> None:
    paper_a = _import_paper(client, "Clinical study A", "The study used the MIMIC-IV dataset for model evaluation.")
    paper_b = _import_paper(client, "Clinical study B", "The study used MIMIC-IV records for a different analysis.")

    response = client.get("/api/v1/evidence/dependency-candidates")
    assert response.status_code == 200, response.text
    candidate = next(item for item in response.json()["candidates"] if {item["paper_a_id"], item["paper_b_id"]} == {paper_a["id"], paper_b["id"]})

    confirmed = client.post(
        "/api/v1/evidence/paper-dependencies",
        json={
            "dependent_paper_id": candidate["paper_a_id"],
            "depends_on_paper_id": candidate["paper_b_id"],
            "relation_type": candidate["relation_type"],
            "provenance_basis": "human_reviewed",
            "rationale": "Human reviewer confirmed both papers describe reuse of MIMIC-IV.",
            "confidence": candidate["confidence"],
        },
    )
    assert confirmed.status_code == 201, confirmed.text

    event = client.post(
        f"/api/v1/sources/papers/{paper_a['id']}/events",
        json={
            "event_type": "metadata_change",
            "description": "A metadata update requires review of the shared dataset record.",
            "source_url": "https://example.org/notice",
            "verification_status": "human_verified",
        },
    )
    assert event.status_code == 201, event.text
    impact = event.json()["impact"]
    assert paper_a["id"] in impact["impacted_paper_ids"]
    assert paper_b["id"] in impact["impacted_paper_ids"]


def test_near_duplicate_abstracts_are_surfaced_for_review(client) -> None:
    abstract = (
        "This retrospective cohort study evaluates predictive model performance in a carefully curated "
        "clinical population. The investigators report outcomes, confidence intervals, model calibration, "
        "error patterns, limitations, and recommendations for further independent validation of the proposed method."
    )
    paper_a = _import_paper(client, "Duplicate candidate A", abstract)
    paper_b = _import_paper(client, "Duplicate candidate B", abstract)

    response = client.get("/api/v1/evidence/dependency-candidates")
    assert response.status_code == 200, response.text
    candidates = [
        item for item in response.json()["candidates"]
        if {item["paper_a_id"], item["paper_b_id"]} == {paper_a["id"], paper_b["id"]}
    ]
    assert candidates
    assert candidates[0]["relation_type"] == "duplicate_or_overlap"
    assert candidates[0]["confidence"] >= 0.68
