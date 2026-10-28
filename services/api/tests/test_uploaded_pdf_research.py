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
    assert snapshot["retrieval_method"] == "crossref_openalex_plus_bm25_local_passages"
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
