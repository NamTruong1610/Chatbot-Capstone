"""GenerationService: numbered context → grounded answer + sources + grounded flag.

Owns the two grounding guarantees the *code* can make deterministically:

- **FR-GEN-06:** if retrieval returned nothing, return the abstention phrase and never call the
  LLM — so an empty context can never yield a hallucinated answer (the core safety property).
- **Abstention detection (docs/06 §3):** exact-substring of the configured phrase after
  whitespace/case canonicalisation. Deliberately NOT fuzzy — a model that *paraphrases* its
  refusal is disobeying the strict_grounded prompt (which says reply EXACTLY the phrase), and
  that non-compliance is a reportable finding, not something to paper over with semantic matching
  (CLAUDE.md rule 5). The phrase is ASCII-only (docs/03 §2.7) so punctuation cannot desync it.

Semantic grounding — is the answer actually supported by the context — is the model's job via
the prompt, and is measured in the evaluation harness. The service does not fake it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from chatbot.config.schema import ResolvedConfig
from chatbot.generation.client import LLMClient, build_llm_client
from chatbot.generation.prompts import load_prompt
from chatbot.retrieval.base import RetrievedChunk


@dataclass(frozen=True)
class GenerationResult:
    """One generated answer: the text, the source URLs behind it, and whether it is grounded."""

    answer: str
    sources: list[str]  # retrieved URLs, deduped + ordered; empty on abstention
    grounded: bool  # True = answered from context; False = abstained (or forced to)


def _norm(text: str) -> str:
    """Collapse whitespace + casefold — canonicalisation, not fuzzy matching (docs/06 §3)."""
    return " ".join(text.split()).casefold()


def is_abstention(answer: str, abstention_phrase: str) -> bool:
    """True if the answer contains the configured refusal phrase (canonicalised substring)."""
    return _norm(abstention_phrase) in _norm(answer)


def _numbered_context(chunks: list[RetrievedChunk]) -> str:
    """Number chunks so the model can cite markers and the prompt shows provenance (FR-GEN-05)."""
    return "\n\n".join(f"[{i}] ({c.source_url})\n{c.text}" for i, c in enumerate(chunks, start=1))


def _dedupe(urls: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        if url and url not in seen:
            seen.add(url)
            out.append(url)
    return out


class GenerationService:
    """Assembles the prompt, calls the injected client, and classifies the result."""

    def __init__(self, cfg: ResolvedConfig, client: LLMClient, system_prompt: str) -> None:
        self._cfg = cfg
        self._client = client
        self._system = system_prompt
        self._abstention = cfg.generation.abstention_phrase

    def generate(self, question: str, chunks: list[RetrievedChunk]) -> GenerationResult:
        # FR-GEN-06: nothing to ground on → refuse without consulting the LLM.
        if not chunks:
            return GenerationResult(answer=self._abstention, sources=[], grounded=False)

        user = f"{_numbered_context(chunks)}\n\nQuestion: {question}"
        answer = self._client.complete(
            system=self._system,
            user=user,
            temperature=self._cfg.generation.temperature,
            max_tokens=self._cfg.generation.max_tokens,
        )
        if is_abstention(answer, self._abstention):
            # A refusal cites nothing — never attach sources to it.
            return GenerationResult(answer=answer, sources=[], grounded=False)
        return GenerationResult(
            answer=answer, sources=_dedupe(c.source_url for c in chunks), grounded=True
        )


def build_generation_service(
    cfg: ResolvedConfig, client: LLMClient | None = None
) -> GenerationService:
    """Load the config's prompt variant and wire the service; builds the real client if none set."""
    system_prompt = load_prompt(
        cfg.generation.prompt_variant, abstention_phrase=cfg.generation.abstention_phrase
    )
    resolved_client = client if client is not None else build_llm_client(cfg.generation)
    return GenerationService(cfg, resolved_client, system_prompt)
