"""POST /api/ingest/private endpoint (Phase 11, FR-API-06) — token guard, success, not-ready.

The isolation itself is proven in tests/unit/test_private_ingest_isolation.py; here we pin the
HTTP surface with a fake service: the write is admin-token-gated (not role-only), a ready domain
returns the chunk count, and an uningested domain 404s.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from chatbot.api.main import create_app
from chatbot.ingestion.pipeline import PrivateIngestResult
from chatbot.pipeline import ChatAnswer, IndexNotReadyError

BODY = {
    "domain_id": "acme-demo", "title": "Compliance Officer", "text": "Dana Fox, tracer XYZZY-9.",
}


class _FakePipeline:
    domain_id = "wyatt-edu"

    def answer(self, question: str, *, role: str | None = None) -> ChatAnswer:
        return ChatAnswer("x", [], True)


class FakePrivateNotes:
    def __init__(self, *, chunks_added: int = 3, raise_not_ready: bool = False) -> None:
        self._chunks_added = chunks_added
        self._raise = raise_not_ready
        self.calls: list[tuple[str, str, str]] = []

    def add(self, domain_id: str, title: str, text: str) -> PrivateIngestResult:
        self.calls.append((domain_id, title, text))
        if self._raise:
            raise IndexNotReadyError(f"domain {domain_id!r} is not ingested")
        return PrivateIngestResult(
            domain_id=domain_id, title=title, chunks_added=self._chunks_added
        )


def _client(notes: Any, token: str | None) -> TestClient:
    return TestClient(
        create_app(
            pipeline=_FakePipeline(),  # type: ignore[arg-type]
            private_note_service=notes,
            admin_token=token,
        )
    )


def test_without_admin_token_configured_fails_closed_503() -> None:
    notes = FakePrivateNotes()
    with _client(notes, token=None) as client:
        resp = client.post("/api/ingest/private", headers={"X-API-Key": "anything"}, json=BODY)
    assert resp.status_code == 503
    assert notes.calls == []  # never reached the service


def test_wrong_or_missing_key_is_rejected() -> None:
    notes = FakePrivateNotes()
    with _client(notes, token="s3cret") as client:
        missing = client.post("/api/ingest/private", json=BODY)
        wrong = client.post("/api/ingest/private", headers={"X-API-Key": "nope"}, json=BODY)
    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert notes.calls == []


def test_valid_key_ingests_and_returns_chunk_count() -> None:
    notes = FakePrivateNotes(chunks_added=4)
    with _client(notes, token="s3cret") as client:
        resp = client.post("/api/ingest/private", headers={"X-API-Key": "s3cret"}, json=BODY)
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "domain_id": "acme-demo", "title": "Compliance Officer",
        "chunks_added": 4, "access_level": "private",
    }
    assert notes.calls == [("acme-demo", "Compliance Officer", "Dana Fox, tracer XYZZY-9.")]


def test_unready_domain_returns_404() -> None:
    notes = FakePrivateNotes(raise_not_ready=True)
    with _client(notes, token="s3cret") as client:
        resp = client.post("/api/ingest/private", headers={"X-API-Key": "s3cret"}, json=BODY)
    assert resp.status_code == 404
    assert "not ingested" in resp.json()["detail"]
