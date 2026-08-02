"""GenerationService grounding + abstention (FR-GEN-04/05/06, docs/06 §3).

The LLM is an injected Protocol, so these run with a FakeLLMClient — no Ollama, no network,
CI-safe. They pin the *plumbing* the service is responsible for; the real grounding quality of
llama3.2 is measured only in the local generation-eval run. The case with teeth is
``test_not_in_context_forces_abstention_without_calling_llm``: retrieval hands the generator
nothing, the fake is rigged to hallucinate if consulted, and the service must refuse *without
ever calling it* (FR-GEN-06) — a naive implementation would call the LLM and return the lie.
"""

from __future__ import annotations

from typing import Any

from chatbot.config.loader import load_config
from chatbot.generation.service import GenerationResult, build_generation_service
from chatbot.retrieval.base import RetrievedChunk

ABSTENTION = "I do not have that information. Please contact us directly."


def _chunk(url: str, text: str, rank: int = 1) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"c{rank}", source_url=url, text=text, score=1.0, rank=rank,
        access_level="public", payload={},
    )


class FakeLLMClient:
    """Records every call and returns a fixed response. Rig it to hallucinate to prove the
    service refuses to consult it when there is nothing to ground on."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def complete(self, *, system: str, user: str, temperature: float, max_tokens: int) -> str:
        self.calls.append(
            {"system": system, "user": user, "temperature": temperature, "max_tokens": max_tokens}
        )
        return self.response


def _svc(fake: FakeLLMClient) -> Any:
    return build_generation_service(load_config("C0-baseline"), fake)


def test_answer_in_context_returns_grounded_answer_with_sources() -> None:
    fake = FakeLLMClient("The Diploma of Business fee is $11,500 [1].")
    chunks = [_chunk("https://x/courses", "Diploma of Business fee is $11,500", 1)]
    res = _svc(fake).generate("How much is the Diploma of Business?", chunks)

    assert isinstance(res, GenerationResult)
    assert res.grounded is True
    assert "$11,500" in res.answer
    assert res.sources == ["https://x/courses"]
    # config-driven + grounding instruction actually reaches the model:
    (call,) = fake.calls
    assert ABSTENTION in call["system"]  # strict_grounded carries the exact abstention phrase
    assert "Diploma of Business fee is $11,500" in call["user"]  # numbered context passed
    assert call["temperature"] == 0.0  # determinism, from config (FR-GEN-08)


def test_not_in_context_forces_abstention_without_calling_llm() -> None:
    # TEETH (FR-GEN-06): nothing retrieved → refuse, and never give the rigged LLM the chance.
    fake = FakeLLMClient("The answer is definitely $42.")  # would hallucinate if consulted
    res = _svc(fake).generate("What is the meaning of life?", [])

    assert res.answer == ABSTENTION  # exact phrase, no paraphrase
    assert res.grounded is False
    assert res.sources == []
    assert fake.calls == []  # the LLM was never called — no chance to hallucinate


def test_model_abstention_is_detected_and_returns_no_sources() -> None:
    # Retrieval was non-empty, but the model (following strict_grounded) returned the phrase.
    fake = FakeLLMClient(ABSTENTION)
    chunks = [_chunk("https://x/about", "Wyatt was established in 2021.", 1)]
    res = _svc(fake).generate("What is the tuition fee?", chunks)

    assert res.grounded is False
    assert res.answer == ABSTENTION
    assert res.sources == []  # no hallucinated sources attached to a refusal
    assert len(fake.calls) == 1  # the LLM WAS consulted (there was context to try)


def test_sources_dedupe_and_preserve_order() -> None:
    fake = FakeLLMClient("Bankstown and Lidcombe [1][2].")
    chunks = [
        _chunk("https://x/courses", "Business courses are at Bankstown.", 1),
        _chunk("https://x/courses", "Tiling is at Lidcombe.", 2),  # same page, one source
        _chunk("https://x/contact", "Call us.", 3),
    ]
    res = _svc(fake).generate("Where are courses taught?", chunks)
    assert res.sources == ["https://x/courses", "https://x/contact"]  # deduped, order kept
