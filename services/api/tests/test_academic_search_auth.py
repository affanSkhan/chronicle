import asyncio
from types import SimpleNamespace

from pydantic import SecretStr

from app.core import config
from app.services import academic_search


def test_openalex_search_sends_configured_key_as_bearer_header(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"results": []}

    class FakeClient:
        async def get(self, url, **kwargs):
            captured["url"] = url
            captured["kwargs"] = kwargs
            return FakeResponse()

    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(openalex_api_key=SecretStr("test-openalex-key")),
    )
    results = asyncio.run(academic_search.search_openalex(FakeClient(), "research evidence", 5))

    assert results == []
    assert captured["url"] == academic_search.OPENALEX_URL
    assert captured["kwargs"]["headers"] == {"Authorization": "Bearer test-openalex-key"}
    assert captured["kwargs"]["params"] == {"search": "research evidence", "per-page": 5}


def test_openalex_search_does_not_send_empty_key(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"results": []}

    class FakeClient:
        async def get(self, url, **kwargs):
            captured["kwargs"] = kwargs
            return FakeResponse()

    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(openalex_api_key=SecretStr("  ")),
    )
    asyncio.run(academic_search.search_openalex(FakeClient(), "research evidence", 5))

    assert "headers" not in captured["kwargs"]
