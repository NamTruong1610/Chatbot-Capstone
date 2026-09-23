"""LLMQueryRewriter: condense a follow-up to a standalone query (FR-GEN-09).

Driven by a fake LLM client — no Ollama, no network. These pin the plumbing the rewriter owns:
when it fires, what transcript it shows the model, and how it cleans and floors the output. The
rewrite *quality* of the real model is a local concern; here we prove the mechanism and its guards.
"""

from __future__ import annotations

from typing import Any

from chatbot.config.loader import load_config
from chatbot.generation.history import Turn
from chatbot.generation.rewrite import build_query_rewriter


class FakeLLMClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def complete(
        self, *, system: str, user: str, temperature: float, max_tokens: int,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        self.calls.append({"system": system, "user": user, "temperature": temperature})
        return self.response


def _rewriter(fake: FakeLLMClient) -> Any:
    return build_query_rewriter(load_config("C0-baseline"), fake)


def test_empty_history_returns_the_question_and_never_calls_the_model() -> None:
    # A first-turn message is already standalone — no history to resolve against, so no LLM call.
    fake = FakeLLMClient("SHOULD NOT BE USED")
    out = _rewriter(fake).rewrite("How much is the Diploma of Business?", [])
    assert out == "How much is the Diploma of Business?"
    assert fake.calls == []


def test_condenses_using_history_and_shows_the_model_the_transcript() -> None:
    fake = FakeLLMClient("How much is the Diploma of Business?")
    history = [Turn(user="Tell me about the Diploma of Business",
                    assistant="It is a 12-month course.")]
    out = _rewriter(fake).rewrite("how much is it?", history)

    assert out == "How much is the Diploma of Business?"
    (call,) = fake.calls
    # The transcript AND the follow-up reach the model, so it can resolve "it".
    assert "Diploma of Business" in call["user"]
    assert "how much is it?" in call["user"]
    # Determinism: the rewrite is pinned to greedy decoding, rule 3.
    assert call["temperature"] == 0.0
    # The condense prompt (not strict_grounded) is the system message.
    assert "standalone search query" in call["system"]


def test_rewrite_temperature_is_pinned_independent_of_generation_temperature() -> None:
    # A serving config may raise generation.temperature for answer style; the rewrite must stay
    # deterministic regardless — it is a precision task with one correct output.
    fake = FakeLLMClient("How much is the Diploma of Business?")
    cfg = load_config("C0-baseline")
    cfg.generation.temperature = 0.9  # would leak into the rewrite if it were not pinned
    history = [Turn(user="Tell me about the Diploma", assistant="A 12-month course.")]
    build_query_rewriter(cfg, fake).rewrite("how much?", history)
    (call,) = fake.calls
    assert call["temperature"] == 0.0  # pinned, not inherited


def test_strips_wrapping_quotes_the_model_may_add() -> None:
    fake = FakeLLMClient('  "How much is the Diploma of Business?"  ')
    history = [Turn(user="Tell me about the Diploma", assistant="A 12-month course.")]
    assert _rewriter(fake).rewrite("how much?", history) == "How much is the Diploma of Business?"


def test_empty_model_output_falls_back_to_the_original_question() -> None:
    # An empty rewrite must never reach retrieval (it would search on ""); the raw question is the
    # safe floor.
    fake = FakeLLMClient("   ")
    history = [Turn(user="Tell me about the Diploma", assistant="A 12-month course.")]
    assert _rewriter(fake).rewrite("how much is it?", history) == "how much is it?"


def test_history_is_bounded_by_history_turns() -> None:
    # C0 history_turns is 8; older exchanges beyond that must not appear in the condense prompt.
    fake = FakeLLMClient("standalone")
    history = [Turn(user=f"q{i}", assistant=f"a{i}") for i in range(10)]
    _rewriter(fake).rewrite("and the price?", history)
    (call,) = fake.calls
    assert "q0" not in call["user"] and "q1" not in call["user"]  # oldest two dropped
    assert "q2" in call["user"] and "q9" in call["user"]  # last eight kept
