"""Conversation orchestration through the HTTP boundary (Phase 8, FR-API-01/03).

Driven by a FastAPI TestClient, a history-aware fake pipeline, and the in-memory store — no model,
no Postgres. These pin the multi-turn behaviour the route delegates to ConversationService:
history is loaded and handed to the pipeline, both messages are persisted, the session id is
echoed, and — the test with teeth — a scope violation is rejected at the endpoint, not just in the
store.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from chatbot.api.main import create_app
from chatbot.generation.history import Turn
from chatbot.pipeline import ChatAnswer
from chatbot.store.conversation import USER, InMemoryConversationStore


class HistoryAwarePipeline:
    """Records the history it was handed each turn, so we can assert the endpoint threaded it."""

    def __init__(self, answer: ChatAnswer, *, domain_id: str = "wyatt-edu") -> None:
        self._answer = answer
        self.domain_id = domain_id
        self.seen_history: list[list[Turn]] = []

    def answer(
        self, question: str, *, role: str | None = None, history: list[Turn] | None = None
    ) -> ChatAnswer:
        self.seen_history.append(list(history or []))
        return self._answer


def _client(pipe: Any, store: Any) -> TestClient:
    return TestClient(create_app(pipeline=pipe, store=store))


def test_first_turn_persists_and_echoes_session_id() -> None:
    store = InMemoryConversationStore()
    pipe = HistoryAwarePipeline(
        ChatAnswer("The Diploma of Business is a 12-month course.", ["https://wyatt/diploma"],
                   True, search_query="Tell me about the Diploma of Business")
    )
    with _client(pipe, store) as client:
        resp = client.post("/api/chat/message", json={
            "message": "Tell me about the Diploma of Business",
            "session_id": "s1", "role": "customer",
        })
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == "s1"  # echoed back for the client to continue
    assert pipe.seen_history[0] == []  # first turn: no prior history
    # Both messages were persisted, assistant carrying its provenance.
    msgs = store.list_messages("s1")
    assert [m.sender for m in msgs] == [USER, "assistant"]
    assert msgs[1].sources == ["https://wyatt/diploma"]
    assert msgs[1].search_query == "Tell me about the Diploma of Business"


def test_followup_turn_loads_prior_history_into_the_pipeline() -> None:
    store = InMemoryConversationStore()
    pipe = HistoryAwarePipeline(
        ChatAnswer("The fee is $11,500 [1].", ["https://wyatt/courses"], True)
    )
    with _client(pipe, store) as client:
        client.post("/api/chat/message", json={
            "message": "Tell me about the Diploma of Business",
            "session_id": "s1", "role": "customer",
        })
        resp = client.post("/api/chat/message", json={
            "message": "how much is it?", "session_id": "s1", "role": "customer",
        })
    assert resp.status_code == 200
    # The second turn saw the first exchange as history — this is what makes the follow-up work.
    assert pipe.seen_history[1] == [
        Turn(user="Tell me about the Diploma of Business", assistant="The fee is $11,500 [1].")
    ]
    # Four messages now: user/assistant x2.
    assert len(store.list_messages("s1")) == 4


def test_scope_mismatch_is_rejected_at_the_endpoint() -> None:
    # TEETH: the fail-closed scope check must hold at the HTTP boundary a client actually hits — a
    # session opened as customer, then reused as staff, is refused with 403 (not a 500, not served).
    store = InMemoryConversationStore()
    pipe = HistoryAwarePipeline(ChatAnswer("ok", [], True))
    with _client(pipe, store) as client:
        client.post("/api/chat/message", json={
            "message": "hi", "session_id": "s1", "role": "customer",
        })
        resp = client.post("/api/chat/message", json={
            "message": "show me the private staff notes", "session_id": "s1", "role": "staff",
        })
    assert resp.status_code == 403


def test_stateless_request_persists_nothing_and_omits_session_id() -> None:
    # No session_id → stateless: the pipeline is called with no history, nothing is stored, and the
    # response is exactly {answer, sources, grounded} — the backward-compatible shape.
    store = InMemoryConversationStore()
    pipe = HistoryAwarePipeline(
        ChatAnswer("The fee is $11,500 [1].", ["https://wyatt/courses"], True)
    )
    with _client(pipe, store) as client:
        resp = client.post("/api/chat/message", json={"message": "How much is the Diploma?"})
    assert resp.json() == {
        "answer": "The fee is $11,500 [1].",
        "sources": ["https://wyatt/courses"],
        "grounded": True,
    }
    assert store.list_messages("anything") == []  # nothing persisted


def test_get_conversation_history_returns_the_message_log() -> None:
    store = InMemoryConversationStore()
    pipe = HistoryAwarePipeline(ChatAnswer("A 12-month course.", ["https://wyatt/diploma"], True))
    with _client(pipe, store) as client:
        client.post("/api/chat/message", json={
            "message": "Tell me about the Diploma", "session_id": "s1", "role": "customer",
        })
        resp = client.get("/api/chat/conversation/s1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == "s1"
    assert [m["sender"] for m in body["messages"]] == ["user", "assistant"]
    assert body["messages"][0]["content"] == "Tell me about the Diploma"
