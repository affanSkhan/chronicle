from app.services.dependency_analysis import summarize_dependency_records


def test_dependency_summary_groups_only_recorded_relationships() -> None:
    papers = [
        {"paper_id": "p1", "title": "Primary study", "doi": "10.1234/primary"},
        {"paper_id": "p2", "title": "Secondary analysis", "doi": "10.1234/secondary"},
        {"paper_id": "p3", "title": "Independent-looking study", "doi": "10.1234/third"},
    ]
    dependencies = [{
        "id": "edge-1",
        "dependent_paper_id": "p2",
        "depends_on_paper_id": "p1",
        "relation_type": "same_dataset",
        "provenance_basis": "human_reviewed",
        "rationale": "The publication explicitly reports reuse of the primary dataset.",
        "confidence": 0.95,
    }]

    summary = summarize_dependency_records(papers, dependencies)

    assert summary["raw_source_count"] == 3
    assert summary["declared_dependency_edge_count"] == 1
    assert summary["evidence_family_count_estimate"] == 2
    assert summary["sources_in_detected_families"] == 2
    assert summary["unclustered_source_count"] == 1
    assert len(summary["detected_clusters"]) == 1
    cluster = summary["detected_clusters"][0]
    assert set(cluster["paper_ids"]) == {"p1", "p2"}
    assert cluster["review_required"] is False
    assert cluster["relationships"][0]["provenance_basis"] == "human_reviewed"
    assert "not proven independent" in summary["interpretation_note"]


def test_inferred_dependency_family_is_explicitly_marked_for_review() -> None:
    summary = summarize_dependency_records(
        [
            {"paper_id": "a", "title": "A"},
            {"paper_id": "b", "title": "B"},
        ],
        [{
            "dependent_paper_id": "b",
            "depends_on_paper_id": "a",
            "relation_type": "derived_from",
            "provenance_basis": "metadata_inferred",
            "rationale": "Potential derivative relationship.",
            "confidence": 0.7,
        }],
    )

    assert len(summary["detected_clusters"]) == 1
    assert summary["detected_clusters"][0]["review_required"] is True
    assert summary["detected_clusters"][0]["relationships"][0]["review_status"] == "candidate"
