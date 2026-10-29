import asyncio
from types import SimpleNamespace

import fitz
from sqlalchemy import select

from app.models.entities import Paper, ResearchRun, User
from app.services import research_pipeline
from conftest import TestingSessionLocal


def _make_pdf(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data


def test_selected_pdf_passages_are_used_in_a_real_research_run(monkeypatch, client) -> None:
    monkeypatch.setattr(research_pipeline, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(
        research_pipeline,
        "get_settings",
        lambda: SimpleNamespace(openai_api_key=None, openai_api_base="https://api.openai.com/v1", openai_model=""),
    )

    async def empty_metadata_search(question: str, limit: int = 10, provider: str = "all") -> dict:
        return {
            "query": question,
            "providers_requested": provider,
            "provider_errors": {},
            "results": [],
        }

    monkeypatch.setattr(research_pipeline, "search_papers", empty_metadata_search)

    upload = client.post(
        "/api/v1/documents/upload",
        files={
            "file": (
                "evidence-provenance.pdf",
                _make_pdf("Evidence provenance connects research claims to exact passages. "
                          "A reproducible evidence graph makes source lineage inspectable."),
                "application/pdf",
            )
        },
    )
    assert upload.status_code == 201, upload.text
    paper_id = upload.json()["paper_id"]
    passages_response = client.get(f"/api/v1/documents/papers/{paper_id}/passages")
    assert passages_response.status_code == 200, passages_response.text
    original_passage_ids = {item["id"] for item in passages_response.json()["passages"]}
    assert original_passage_ids

    created = client.post(
        "/api/v1/research/runs",
        json={
            "question": "How does evidence provenance make research claims inspectable?",
            "mode": "quick",
            "max_sources": 5,
            "source_paper_ids": [paper_id],
            "execute": False,
        },
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]
    assert created.json()["demo"] is True

    asyncio.run(research_pipeline.execute_research_run(run_id))

    with TestingSessionLocal() as db:
        run = db.get(ResearchRun, run_id)
        assert run is not None
        assert run.status == "completed"
        report = db.scalar(
            select(research_pipeline.ReportVersion)
            .where(research_pipeline.ReportVersion.run_id == run_id)
            .order_by(research_pipeline.ReportVersion.version_number.desc())
        )
        assert report is not None
        snapshot = report.evidence_snapshot

    assert snapshot["source_paper_ids"] == [paper_id]
    assert snapshot["retrieval_method"] == "bm25_lexical"
    assert snapshot["retrieval_metadata"]["semantic_status"] == "not_configured"
    assert snapshot["selected_context_count"] >= 1
    assert set(snapshot["selected_context_passage_ids"]).issubset(original_passage_ids)
    assert set(snapshot["passage_ids"]) & original_passage_ids
    assert "User-uploaded PDF" in report.content_markdown
    assert "PDF evidence passage" in report.content_markdown
    assert "BM25" in report.content_markdown


def test_research_run_cannot_attach_another_users_pdf(client) -> None:
    with TestingSessionLocal() as db:
        owner_id = db.scalar(select(User.id).where(User.email == "fixture-user@example.test"))
        assert owner_id
        foreign_user = User(
            email="foreign-upload-owner@example.test",
            password_hash="test-only-not-used",
        )
        db.add(foreign_user)
        db.flush()
        foreign_pdf = Paper(
            owner_user_id=foreign_user.id,
            title="Private research PDF",
            source_provider="upload",
            external_id="foreign-file",
        )
        db.add(foreign_pdf)
        db.commit()
        foreign_id = foreign_pdf.id

    response = client.post(
        "/api/v1/research/runs",
        json={
            "question": "Can another account's PDF be attached to my run?",
            "mode": "quick",
            "source_paper_ids": [foreign_id],
            "execute": False,
        },
    )
    assert response.status_code == 404
    assert "selected PDF documents" in response.json()["detail"]


def test_research_run_rejects_more_than_five_pdf_attachments(client) -> None:
    response = client.post(
        "/api/v1/research/runs",
        json={
            "question": "How should a bounded PDF evidence budget behave?",
            "mode": "quick",
            "source_paper_ids": ["a", "b", "c", "d", "e", "f"],
            "execute": False,
        },
    )
    assert response.status_code == 422


def test_permanent_pdf_deletion_removes_passages_and_redacts_derived_reports(monkeypatch, client) -> None:
    from pathlib import Path

    monkeypatch.setattr(research_pipeline, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(
        research_pipeline,
        "get_settings",
        lambda: SimpleNamespace(openai_api_key=None, openai_api_base="https://api.openai.com/v1", openai_model=""),
    )

    async def empty_metadata_search(question: str, limit: int = 10, provider: str = "all") -> dict:
        return {
            "query": question,
            "providers_requested": provider,
            "provider_errors": {},
            "results": [],
        }

    monkeypatch.setattr(research_pipeline, "search_papers", empty_metadata_search)
    upload = client.post(
        "/api/v1/documents/upload",
        files={"file": ("private-source.pdf", _make_pdf("Private phrase: cobalt river. This source supports careful evidence traceability."), "application/pdf")},
    )
    assert upload.status_code == 201, upload.text
    paper_id = upload.json()["paper_id"]
    passage_payload = client.get(f"/api/v1/documents/papers/{paper_id}/passages").json()
    passage_id = passage_payload["passages"][0]["id"]

    created = client.post(
        "/api/v1/research/runs",
        json={
            "question": "How does this PDF support evidence traceability?",
            "mode": "quick",
            "source_paper_ids": [paper_id],
            "execute": False,
        },
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["id"]
    asyncio.run(research_pipeline.execute_research_run(run_id))

    claim_response = client.post(
        "/api/v1/evidence/claims",
        json={"run_id": run_id, "statement": "The private source supports evidence traceability."},
    )
    assert claim_response.status_code == 201, claim_response.text
    claim_id = claim_response.json()["id"]
    relation_response = client.post(
        f"/api/v1/evidence/claims/{claim_id}/relations",
        json={
            "passage_id": passage_id,
            "relation_type": "supports",
            "provenance_basis": "source_documented",
            "reviewer_status": "unreviewed",
            "rationale": "Direct evidence passage from the uploaded source.",
        },
    )
    assert relation_response.status_code == 201, relation_response.text

    with TestingSessionLocal() as db:
        from app.models.entities import Conclusion, ConclusionEvidenceRelation, ReportVersion
        report = db.scalar(select(ReportVersion).where(ReportVersion.run_id == run_id))
        assert report is not None
        conclusion = Conclusion(
            run_id=run_id,
            report_version_id=report.id,
            statement="The cobalt river source supports evidence traceability.",
            relation_type="supports",
            reviewer_status="needs_review",
            provenance_basis="model_inferred",
            rationale="Test-only synthetic conclusion derived from the uploaded PDF.",
            metadata_snapshot={"source_passage_ids": [passage_id]},
        )
        db.add(conclusion)
        db.flush()
        db.add(ConclusionEvidenceRelation(
            conclusion_id=conclusion.id,
            claim_id=claim_id,
            passage_id=passage_id,
            relation_type="supports",
            provenance_basis="model_inferred",
            reviewer_status="needs_review",
            rationale="Test-only evidence edge.",
        ))
        report.evidence_snapshot = {**(report.evidence_snapshot or {}), "conclusion_ids": [conclusion.id]}
        db.commit()

    with TestingSessionLocal() as db:
        from app.models.entities import Paper
        paper = db.get(Paper, paper_id)
        assert paper is not None
        local_original_path = Path(paper.source_file_path)
        assert local_original_path.exists()

    deleted = client.delete(f"/api/v1/documents/papers/{paper_id}")
    assert deleted.status_code == 200, deleted.text
    deletion_result = deleted.json()
    assert deletion_result["deleted"] is True
    assert deletion_result["deleted_passage_count"] >= 1
    assert deletion_result["deleted_claim_count"] >= 1
    assert deletion_result["redacted_report_version_count"] >= 1
    assert not local_original_path.exists()

    assert client.get(f"/api/v1/documents/papers/{paper_id}/passages").status_code == 404
    assert all(item["id"] != paper_id for item in client.get("/api/v1/sources/papers").json())
    remaining_claims = client.get(f"/api/v1/evidence/runs/{run_id}/claims")
    assert remaining_claims.status_code == 200, remaining_claims.text
    assert all(item["id"] != claim_id for item in remaining_claims.json())

    reports = client.get(f"/api/v1/evidence/runs/{run_id}/reports")
    assert reports.status_code == 200, reports.text
    assert all(report["evidence_snapshot"].get("redacted") is True for report in reports.json())
    assert all("cobalt river" not in report["content_markdown"].lower() for report in reports.json())

    passport = client.get(f"/api/v1/evidence/runs/{run_id}/passport?format=json")
    assert passport.status_code == 200, passport.text
    assert all(item["id"] != paper_id for item in passport.json()["papers"])
    assert all(item["id"] != claim_id for item in passport.json()["claims"])
    assert passport.json()["conclusions"] == []
    assert "cobalt river" not in passport.text.lower()


def test_permanent_pdf_deletion_is_owner_scoped(client) -> None:
    with TestingSessionLocal() as db:
        foreign_user = User(email="foreign-pdf-owner@example.test", password_hash="test-only-not-used")
        db.add(foreign_user)
        db.flush()
        foreign_pdf = Paper(
            owner_user_id=foreign_user.id,
            title="Someone else's PDF",
            source_provider="upload",
            external_id="not-a-real-file",
            source_file_path=None,
        )
        db.add(foreign_pdf)
        db.commit()
        foreign_id = foreign_pdf.id

    response = client.delete(f"/api/v1/documents/papers/{foreign_id}")
    assert response.status_code == 404
