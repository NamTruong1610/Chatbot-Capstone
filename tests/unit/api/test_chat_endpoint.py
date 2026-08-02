"""Chat endpoint via FastAPI TestClient + a fake pipeline — no store, no model, no Ollama in CI.

The route must own no retrieve→generate logic: it just calls the injected ChatPipeline and shapes
the response. These tests drive it end-to-end over HTTP with a fake pipeline.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from chatbot.api.main import create_app
from chatbot.pipeline import ChatAnswer


class FakePipeline:
    """Stands in for ChatPipeline: fixed answer, records the question it was asked."""

    def __init__(self, answer: ChatAnswer, *, domain_id: str = "wyatt-edu") -> None:
        self._answer = answer
        self.domain_id = domain_id
        self.asked: list[str] = []

    def answer(self, question: str, *, role: str | None = None) -> ChatAnswer:
        self.asked.append(question)
        return self._answer


def _client(pipeline: FakePipeline) -> TestClient:
    return TestClient(create_app(pipeline=pipeline))  # type: ignore[arg-type]


def test_chat_message_returns_answer_sources_and_grounded() -> None:
    pipe = FakePipeline(ChatAnswer("The fee is $11,500 [1].", ["https://x/courses"], True))
    with _client(pipe) as client:
        resp = client.post("/api/chat/message", json={"message": "How much is the Diploma?"})
    assert resp.status_code == 200
    assert resp.json() == {
        "answer": "The fee is $11,500 [1].",
        "sources": ["https://x/courses"],
        "grounded": True,
    }
    assert pipe.asked == ["How much is the Diploma?"]


def test_abstention_surfaces_as_grounded_false_with_no_sources() -> None:
    phrase = "I do not have that information. Please contact us directly."
    pipe = FakePipeline(ChatAnswer(phrase, [], False))
    with _client(pipe) as client:
        resp = client.post("/api/chat/message", json={"message": "Do you offer scholarships?"})
    body = resp.json()
    assert body["grounded"] is False
    assert body["sources"] == []
    assert body["answer"] == phrase


def test_empty_message_is_rejected() -> None:
    pipe = FakePipeline(ChatAnswer("x", [], True))
    with _client(pipe) as client:
        resp = client.post("/api/chat/message", json={"message": ""})
    assert resp.status_code == 422  # pydantic min_length=1


def test_wrong_domain_is_rejected() -> None:
    pipe = FakePipeline(ChatAnswer("x", [], True), domain_id="wyatt-edu")
    with _client(pipe) as client:
        resp = client.post(
            "/api/chat/message", json={"message": "hi", "domain_id": "other-domain"}
        )
    assert resp.status_code == 400


def test_health_reports_active_config() -> None:
    pipe = FakePipeline(ChatAnswer("x", [], True))
    with _client(pipe) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["config_id"] == "C0-baseline"  # FR-API-04
    assert body["domain_id"] == "wyatt-edu"
