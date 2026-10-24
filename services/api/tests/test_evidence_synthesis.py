import asyncio
import json

from app.services import evidence_synthesis


def test_synthesis_filters_opportunities_without_valid_evidence_ids(monkeypatch):
    payload = {
        "executive_summary": "A short evidence-bounded summary of the supplied source.",
        "findings": [{
            "statement": "The supplied study reports a measurable outcome.",
            "evidence_passage_ids": ["passage-1"],
            "relation_type": "qualifies",
            "context_note": "Only an abstract passage is available.",
        }],
        "study_characterizations": [],
        "disagreements": [],
        "limitations": ["The retrieved passages may not cover every relevant paper."],
        "candidate_research_questions": ["How does the outcome vary across populations?"],
        "research_opportunities": [
            {
                "question": "Does the outcome persist across a different population?",
                "rationale": "The retrieved passage reports one context but leaves the generalisability question open.",
                "evidence_passage_ids": ["passage-1"],
                "prior_art_search_queries": ["outcome external validation population comparison"],
                "alternative_explanations": ["The observed result may be specific to the original cohort."],
                "falsification_plan": "Pre-register an external validation study and test whether the effect persists.",
            },
            {
                "question": "Does a second effect exist?",
                "rationale": "The model generated this candidate without valid source support.",
                "evidence_passage_ids": ["unknown-passage"],
                "prior_art_search_queries": ["second effect research"],
                "alternative_explanations": ["Confounding may explain the association."],
                "falsification_plan": "Test the claim in a preregistered independent dataset.",
            },
        ],
        "uncertainty_statement": "Evidence is limited to the supplied abstract passage.",
    }

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None
        def json(self):
            return {"choices": [{"message": {"content": json.dumps(payload)}}]}

    class FakeClient:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
        async def post(self, url, json=None):
            captured["payload"] = json
            return FakeResponse()

    monkeypatch.setattr(evidence_synthesis.httpx, "AsyncClient", FakeClient)
    result = asyncio.run(evidence_synthesis.synthesize_evidence(
        question="How does the outcome vary across populations?",
        passages=[{"id": "passage-1", "paper_title": "Study A", "text": "The study reports an outcome in one cohort."}],
        api_key="test-key",
        api_base="https://model.example/v1",
        model="test-model",
    ))

    opportunities = result["research_opportunities"]
    assert len(opportunities) == 1
    assert opportunities[0]["evidence_passage_ids"] == ["passage-1"]
    assert opportunities[0]["review_status"] == "requires_prior_art_review"
    assert "falsification_plan" in opportunities[0]
    system_prompt = captured["payload"]["messages"][0]["content"]
    assert "untrusted quoted data" in system_prompt
    assert result["validated_source_references"] is True
