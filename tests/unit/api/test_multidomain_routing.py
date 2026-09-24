"""Multi-domain serving (Phase 9): one server queries any ingested business.

Two levels:

- PipelineRegistry unit tests — the load-bearing guarantees: a pipeline is built once per domain
  and cached (no rebuild per request), and an uningested domain propagates IndexNotReadyError
  (the fingerprint guard), so you cannot chat with a business that is not ready.
- Endpoint tests — a request for a second domain is routed and answered; an uningested domain
  fails cleanly with 404; the default domain is untouched.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from chatbot.api.main import create_app
from chatbot.api.pipeline_registry import PipelineRegistry
from chatbot.config.loader import load_config
from chatbot.pipeline import ChatAnswer, IndexNotReadyError
from chatbot.store.conversation import InMemoryConversationStore


class FakePipeline:
    def __init__(self, domain_id: str) -> None:
        self.domain_id = domain_id

    def answer(
        self, question: str, *, role: str | None = None, history: Any = None
    ) -> ChatAnswer:
        return ChatAnswer(f"answer from {self.domain_id}", [f"https://{self.domain_id}"], True)


def _fake_builder(cfg: Any, domain_id: str) -> Any:
    return FakePipeline(domain_id)


# --- PipelineRegistry unit tests ---


def test_registry_builds_once_and_caches_per_domain() -> None:
    calls: list[str] = []

    def counting_builder(cfg: Any, domain_id: str) -> Any:
        calls.append(domain_id)
        return FakePipeline(domain_id)

    reg = PipelineRegistry(load_config("C0-baseline"), builder=counting_builder)
    first = reg.get("cutpro")
    second = reg.get("cutpro")  # second request to the same domain
    assert first is second  # same cached instance — no rebuild of embedder/retriever/store
    assert calls == ["cutpro"]  # the builder ran exactly once
    reg.get("austral-eng")
    assert calls == ["cutpro", "austral-eng"]  # a different domain builds once more


def test_registry_propagates_index_not_ready_for_an_uningested_domain() -> None:
    def guard_builder(cfg: Any, domain_id: str) -> Any:
        raise IndexNotReadyError(f"no index for {domain_id}")

    reg = PipelineRegistry(load_config("C0-baseline"), builder=guard_builder)
    with pytest.raises(IndexNotReadyError):
        reg.get("never-ingested")


# --- endpoint routing tests ---


def _multidomain_client(registry: PipelineRegistry) -> TestClient:
    default_pipe = FakePipeline("wyatt-edu")
    app = create_app(
        pipeline=default_pipe,  # type: ignore[arg-type]
        store=InMemoryConversationStore(),
        pipeline_registry=registry,
    )
    return TestClient(app)


def test_second_domain_is_routed_and_answered() -> None:
    registry = PipelineRegistry(load_config("C0-baseline"), builder=_fake_builder)
    client = _multidomain_client(registry)
    with client:
        default = client.post("/api/chat/message", json={"message": "hi"})
        cutpro = client.post("/api/chat/message", json={"message": "hi", "domain_id": "cutpro"})
    assert default.json()["answer"] == "answer from wyatt-edu"  # default path unchanged
    assert cutpro.json()["answer"] == "answer from cutpro"  # the added business is queryable


def test_uningested_domain_returns_404_not_a_crash() -> None:
    def guard_builder(cfg: Any, domain_id: str) -> Any:
        raise IndexNotReadyError(f"no index for {domain_id}")

    registry = PipelineRegistry(load_config("C0-baseline"), builder=guard_builder)
    client = _multidomain_client(registry)
    with client:
        resp = client.post("/api/chat/message", json={"message": "hi", "domain_id": "ghost"})
    assert resp.status_code == 404
    assert "not ingested" in resp.json()["detail"]


def test_default_domain_does_not_touch_the_registry() -> None:
    calls: list[str] = []

    def recording_builder(cfg: Any, domain_id: str) -> Any:
        calls.append(domain_id)
        return FakePipeline(domain_id)

    registry = PipelineRegistry(load_config("C0-baseline"), builder=recording_builder)
    client = _multidomain_client(registry)
    with client:
        client.post("/api/chat/message", json={"message": "hi"})  # default domain
        client.post("/api/chat/message", json={"message": "hi", "domain_id": "wyatt-edu"})
    assert calls == []  # the default is served by the pre-built pipeline, never the registry
