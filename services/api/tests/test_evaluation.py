import pytest

from app.services.evaluation import classification_metrics, evaluate_records, set_retrieval_metrics


def test_classification_metrics_for_relation_labels() -> None:
    metrics = classification_metrics(
        expected=["supports", "contradicts", "qualifies"],
        predicted=["supports", "supports", "qualifies"],
        labels=["supports", "contradicts", "qualifies"],
    )
    assert metrics["sample_count"] == 3
    assert metrics["accuracy"] == pytest.approx(2 / 3)
    assert metrics["per_class"]["supports"]["true_positive"] == 1
    assert metrics["per_class"]["supports"]["false_positive"] == 1
    assert metrics["per_class"]["contradicts"]["false_negative"] == 1


def test_temporal_impact_retrieval_metrics() -> None:
    metrics = set_retrieval_metrics(
        expected_ids=["claim-a", "claim-b", "claim-c"],
        predicted_ids=["claim-b", "claim-c", "claim-d"],
    )
    assert metrics["true_positive"] == 2
    assert metrics["false_positive"] == 1
    assert metrics["false_negative"] == 1
    assert metrics["precision"] == pytest.approx(2 / 3)
    assert metrics["recall"] == pytest.approx(2 / 3)
    assert metrics["f1"] == pytest.approx(2 / 3)


def test_evaluation_combines_available_metric_families() -> None:
    metrics = evaluate_records([
        {
            "expected_relation": "supports",
            "predicted_relation": "supports",
            "expected_impacted_ids": ["claim-1", "claim-2"],
            "predicted_impacted_ids": ["claim-1"],
            "expected_dependency_edges": ["paper-a->paper-b"],
            "predicted_dependency_edges": ["paper-a->paper-b", "paper-c->paper-d"],
        }
    ], dataset_name="curated-pilot-v1")
    assert metrics["dataset_name"] == "curated-pilot-v1"
    assert metrics["relation_classification"]["accuracy"] == 1
    assert metrics["temporal_impact"]["recall"] == pytest.approx(0.5)
    assert metrics["dependency_retrieval"]["precision"] == pytest.approx(0.5)


def test_evaluation_rejects_misaligned_or_empty_classification_data() -> None:
    with pytest.raises(ValueError):
        classification_metrics(["supports"], ["supports", "contradicts"])
    with pytest.raises(ValueError):
        classification_metrics([], [])
    with pytest.raises(ValueError):
        evaluate_records([])


def test_ranked_passage_metrics_compute_mrr_precision_recall_and_ndcg() -> None:
    from app.services.evaluation import ranked_passage_retrieval_metrics

    metrics = ranked_passage_retrieval_metrics(
        expected_ids=["p1", "p3"],
        ranked_ids=["p2", "p3", "p1", "p3"],
        ks=(1, 3),
    )
    assert metrics["ranked_count"] == 3
    assert metrics["mrr"] == pytest.approx(0.5)
    assert metrics["precision_at_1"] == 0
    assert metrics["recall_at_1"] == 0
    assert metrics["precision_at_3"] == pytest.approx(2 / 3)
    assert metrics["recall_at_3"] == 1
    assert 0 < metrics["ndcg_at_3"] <= 1


def test_evaluate_records_aggregates_ranked_passage_metrics_per_query() -> None:
    metrics = evaluate_records([
        {"record_id": "q1", "expected_passage_ids": ["p1"], "predicted_ranked_passage_ids": ["p1", "p2"]},
        {"record_id": "q2", "expected_passage_ids": ["p3"], "predicted_ranked_passage_ids": ["p4", "p3"]},
    ], dataset_name="retrieval-pilot-v1")
    ranking = metrics["ranked_passage_retrieval"]
    assert ranking["sample_count"] == 2
    assert ranking["macro_mean"]["mrr"] == pytest.approx(0.75)
    assert ranking["macro_mean"]["recall_at_3"] == 1


def test_evaluation_reports_claim_support_citations_grounding_and_temporal_false_alarms() -> None:
    metrics = evaluate_records([
        {
            "record_id": "event-1",
            "expected_support_passage_ids": ["p1", "p2"],
            "predicted_support_passage_ids": ["p1", "p3"],
            "expected_impacted_ids": ["claim-a", "claim-b"],
            "predicted_impacted_ids": ["claim-a", "claim-c"],
            "expected_high_severity_impacted_ids": ["claim-b"],
            "predicted_high_severity_impacted_ids": [],
            "citation_count": 4,
            "supported_citation_count": 3,
            "claim_count": 2,
            "claims_with_citations": 2,
            "grounded_claim_count": 1,
            "detection_latency_seconds": 120,
        },
        {
            "record_id": "event-2",
            "expected_support_passage_ids": ["p4"],
            "predicted_support_passage_ids": ["p4"],
            "expected_impacted_ids": [],
            "predicted_impacted_ids": ["claim-x"],
            "expected_high_severity_impacted_ids": [],
            "predicted_high_severity_impacted_ids": [],
            "citation_count": 0,
            "supported_citation_count": 0,
            "claim_count": 1,
            "claims_with_citations": 0,
            "grounded_claim_count": 0,
        },
    ], dataset_name="labelled-temporal-pilot-v1")
    assert metrics["claim_support_retrieval"]["macro_mean"]["precision"] == pytest.approx(0.75)
    assert metrics["citation_quality"]["macro_mean"]["citation_support_precision"] == pytest.approx(0.375)
    assert metrics["passage_grounding"]["grounded_claim_rate"] == pytest.approx(1 / 3)
    assert metrics["temporal_impact_per_event"]["sample_count"] == 2
    assert metrics["temporal_impact_per_event"]["false_alarms_per_source_event"] == pytest.approx(1.0)
    assert metrics["high_severity_temporal_impact"]["missed_high_severity_impacts"] == 1
    assert metrics["detection_latency"]["mean_seconds"] == 120
