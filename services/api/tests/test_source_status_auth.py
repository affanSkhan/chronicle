import asyncio
from types import SimpleNamespace

from pydantic import SecretStr

from app.core import config
from app.services import source_status


def test_openalex_status_request_uses_key_only_for_openalex(monkeypatch):
    calls = []

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class FakeClient:
        def __init__(self, **kwargs):
            self.default_headers = kwargs.get("headers", {})

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, **kwargs):
            calls.append({"url": url, "kwargs": kwargs, "defaults": self.default_headers})
            if url == "https://api.crossref.org/works/10.5555/example":
                return FakeResponse({"message": {"update-to": []}})
            return FakeResponse({"results": []})

    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(openalex_api_key=SecretStr("test-openalex-key")),
    )
    monkeypatch.setattr(source_status.httpx, "AsyncClient", FakeClient)

    result = asyncio.run(source_status.fetch_paper_status_signals("10.5555/example"))

    assert result["providers"] == {"crossref": "ok", "openalex": "not_found"}
    crossref_call, openalex_call = calls
    assert crossref_call["url"].startswith("https://api.crossref.org/")
    assert "headers" not in crossref_call["kwargs"]
    assert "Authorization" not in crossref_call["defaults"]
    assert openalex_call["url"] == "https://api.openalex.org/works"
    assert openalex_call["kwargs"]["headers"] == {"Authorization": "Bearer test-openalex-key"}
    assert "api_key" not in openalex_call["kwargs"].get("params", {})
