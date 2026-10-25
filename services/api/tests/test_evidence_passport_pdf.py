import fitz


def test_evidence_passport_can_be_exported_as_searchable_pdf(client) -> None:
    run_response = client.post(
        "/api/v1/research/runs",
        json={
            "question": "How should source updates affect saved research conclusions?",
            "mode": "forensic",
        },
    )
    assert run_response.status_code == 201, run_response.text
    run_id = run_response.json()["id"]

    report_response = client.post(
        f"/api/v1/evidence/runs/{run_id}/reports",
        json={
            "title": "PDF export regression report",
            "content_markdown": "PDF export regression sentinel: source updates require human reassessment.",
        },
    )
    assert report_response.status_code == 201, report_response.text

    response = client.get(f"/api/v1/evidence/runs/{run_id}/passport?format=pdf")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/pdf")
    assert 'attachment; filename="chronicle-evidence-passport-' in response.headers["content-disposition"]
    assert response.content.startswith(b"%PDF")

    document = fitz.open(stream=response.content, filetype="pdf")
    try:
        assert len(document) >= 1
        extracted_text = "\n".join(page.get_text() for page in document)
    finally:
        document.close()

    assert "Chronicle Evidence Passport" in extracted_text
    assert "Research question" in extracted_text
    assert "Interpretation limitations" in extracted_text
    assert "PDF export regression sentinel" in extracted_text


def test_evidence_passport_rejects_unknown_export_format(client) -> None:
    run_response = client.post(
        "/api/v1/research/runs",
        json={"question": "How can evidence lineage be tested?", "mode": "quick"},
    )
    assert run_response.status_code == 201, run_response.text

    response = client.get(
        f"/api/v1/evidence/runs/{run_response.json()['id']}/passport?format=html"
    )
    assert response.status_code == 422
