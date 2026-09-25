"""GET /api/conversations (Phase 12, FR-API-07) — the conversation browser's list endpoint.

Driven by a real ConversationService over the in-memory store (no Postgres), so the route → service
→ store path is exercised end to end. Proves the list is scoped to (domain_id, role), most-recent
first, and carries the fields the sidebar + resume need.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from chatbot.api.main import create_app
from chatbot.pipeline import ChatAnswer
from chatbot.store.conversation import ASSISTANT, USER, InMemoryConversationStore


class _FakePipeline:
    domain_id = "wyatt-edu"

    def answer(self, question: str, *, role: str | None = None) -> ChatAnswer:
        return ChatAnswer("x", [], True)


def _seed(store: InMemoryConversationStore, cid: str, domain: str, role: str, q: str) -> None:
    store.open_conversation(cid, domain, role)
    store.append_message(cid, sender=USER, content=q)
    store.append_message(cid, sender=ASSISTANT, content=f"reply: {q}")


def test_lists_scoped_conversations_most_recent_first() -> None:
    store = InMemoryConversationStore()
    _seed(store, "a", "wyatt-edu", "customer", "first")
    _seed(store, "b", "wyatt-edu", "customer", "second")  # more recent
    _seed(store, "s", "wyatt-edu", "staff", "staff-only")  # different role
    with TestClient(create_app(pipeline=_FakePipeline(), store=store)) as client:  # type: ignore[arg-type]
        resp = client.get(
            "/api/conversations", params={"domain_id": "wyatt-edu", "role": "customer"}
        )
    assert resp.status_code == 200
    convos = resp.json()["conversations"]
    assert [c["session_id"] for c in convos] == ["b", "a"]  # scoped + most recent first
    assert convos[0]["title"] == "second"
    assert convos[0]["preview"] == "reply: second"
    assert convos[0]["message_count"] == 2
    assert convos[0]["domain_id"] == "wyatt-edu" and convos[0]["role"] == "customer"


def test_empty_scope_returns_empty_list() -> None:
    store = InMemoryConversationStore()
    _seed(store, "a", "wyatt-edu", "customer", "hi")
    with TestClient(create_app(pipeline=_FakePipeline(), store=store)) as client:  # type: ignore[arg-type]
        resp = client.get("/api/conversations", params={"domain_id": "cutpro", "role": "customer"})
    assert resp.status_code == 200
    assert resp.json()["conversations"] == []


def test_stateless_server_returns_empty_list() -> None:
    # No store injected → stateless → empty (the browser just shows nothing, no error).
    with TestClient(create_app(pipeline=_FakePipeline())) as client:  # type: ignore[arg-type]
        resp = client.get(
            "/api/conversations", params={"domain_id": "wyatt-edu", "role": "customer"}
        )
    assert resp.status_code == 200
    assert resp.json()["conversations"] == []
