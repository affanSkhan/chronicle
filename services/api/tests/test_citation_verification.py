import asyncio
from types import SimpleNamespace

from app.services import citation_verification
from app.services.citation_verification import CitationVerification
from pydantic import ValidationError
import pytest


def test_verification_schema_accepts_explicit_verdict_and_source_ids():
    result = CitationVerification.model_validate({
        "verdict": "supported",
        "rationale": "The abstract directly reports the stated outcome.",
        "evidence_passage_ids": ["passage-1"],
        "context_note": "The finding is limited to the reported study population.",
        "uncertainty_notes": ["Only the abstract was assessed."],
    })
    assert result.verdict == "supported"
    assert result.evidence_passage_ids == ["passage-1"]


def test_verification_schema_rejects_unsupported_verdict():
    with pytest.raises(ValidationError):
        CitationVerification.model_validate({
            "verdict": "definitely_true",
            "rationale": "The model says so.",
            "evidence_passage_ids": [],
        })


def test_verifier_downgrades_confident_verdict_without_valid_passage_pointer(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None
        def json(self):
            return {
                "choices": [{
                    "message": {"content": '{"verdict":"supported","rationale":"Looks supported.","evidence_passage_ids":["unknown-id"],"context_note":null,"uncertainty_notes":[]}'}
                }]
            }

    class FakeClient:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(citation_verification.httpx, "AsyncClient", FakeClient)
    result = asyncio.run(citation_verification.verify_claim_with_llm(
        claim_statement="The intervention improves the measured outcome.",
        claim_scope={},
        passages=[{"id":"passage-1", "text":"The abstract does not say that."}],
        api_key="test-key",
        api_base="https://model.example/v1",
        model="test-model",
    ))
    assert result["verdict"] == "unverifiable"
    assert result["evidence_passage_ids"] == []
    assert result["uncertainty_notes"]


def test_verifier_treats_provider_output_as_structured_not_plain_text(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None
        def json(self):
            return {
                "choices": [{
                    "message": {"content": '{"verdict":"partially_supported","rationale":"One aspect is reported.","evidence_passage_ids":["passage-1"],"context_note":"Limited population","uncertainty_notes":["Abstract only."]}'}
                }]
            }

    class FakeClient:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
        async def post(self, url, json=None, **kwargs):
            captured["body"] = json
            return FakeResponse()

    monkeypatch.setattr(citation_verification.httpx, "AsyncClient", FakeClient)
    result = asyncio.run(citation_verification.verify_claim_with_llm(
        claim_statement="The intervention improves the measured outcome.",
        claim_scope={},
        passages=[{"id":"passage-1", "text":"One outcome improved in the measured cohort."}],
        api_key="test-key",
        api_base="https://model.example/v1",
        model="test-model",
    ))
    assert result["verdict"] == "partially_supported"
    assert result["evidence_passage_ids"] == ["passage-1"]
    assert "reasoning_effort" not in captured["body"]
    assert captured["body"]["temperature"] == 0
    assert captured["body"]["max_tokens"] == 900
