"""Query rewriting: condense a context-dependent follow-up into a standalone retrieval query.

The engineering crux of multi-turn RAG (FR-GEN-09). A follow-up like "how much is it?" embeds to
nothing useful — "it" has no referent — so retrieval on the raw message fails. This stage uses the
conversation history to rewrite the follow-up into a self-contained query ("how much is the Diploma
of Business?") *before* retrieval. Retrieval then runs on the rewrite; generation still sees the
original question plus history (``service.py``).

It reuses the generation LLM client (decision 8: prefer boring — one model, one transport); only the
prompt differs (``conversation.rewrite_prompt_variant``). The call is deterministic at
``generation.temperature`` (0.0 in every eval config), so the same follow-up + history rewrites to
the same query on a re-run (CLAUDE.md rule 3).

Crucially, this is only ever invoked when there IS history: the pipeline calls it under
``if history``. A single-shot request (every RQ eval) never reaches here, so retrieval sees the raw
question byte-for-byte and the measured numbers are untouched.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from chatbot.config.schema import ResolvedConfig
from chatbot.generation.client import LLMClient, build_llm_client
from chatbot.generation.history import Turn
from chatbot.generation.prompts import load_named_prompt

# Query rewriting is a precision task with one correct output — the standalone form of the
# follow-up. It must be reproducible (CLAUDE.md rule 3), so it is pinned to greedy decoding
# regardless of generation.temperature: an answer-generation temperature (which a serving config
# may raise for style) must never leak into retrieval and make the rewrite non-deterministic.
# This is a determinism invariant, not a tunable pipeline parameter, so it is fixed here.
_REWRITE_TEMPERATURE = 0.0


@runtime_checkable
class QueryRewriter(Protocol):
    """Turns (follow-up question, conversation history) into a standalone query string."""

    def rewrite(self, question: str, history: list[Turn]) -> str: ...


def _format_history(turns: list[Turn]) -> str:
    """Render the exchanges as a plain transcript the model can resolve references against."""
    lines: list[str] = []
    for turn in turns:
        lines.append(f"User: {turn.user}")
        lines.append(f"Assistant: {turn.assistant}")
    return "\n".join(lines)


def _clean(rewritten: str, *, fallback: str) -> str:
    """Strip whitespace and any wrapping quotes the model added; fall back if it returned nothing.

    An empty rewrite must never reach retrieval (it would retrieve on ""); the original question is
    the safe floor — worse than a good rewrite, but never worse than the raw follow-up would be.
    """
    cleaned = rewritten.strip().strip('"').strip("'").strip()
    return cleaned or fallback


class LLMQueryRewriter:
    """Condenses a follow-up via the generation model, using the configured rewrite prompt."""

    def __init__(self, cfg: ResolvedConfig, client: LLMClient, system_prompt: str) -> None:
        self._client = client
        self._system = system_prompt
        # max_tokens is reused from generation (a length bound, plenty for a short query);
        # temperature is pinned to 0.0 above — the rewrite never inherits a nonzero answer
        # temperature. history_turns bounds how much context to condense on.
        self._max_tokens = cfg.generation.max_tokens
        self._history_turns = cfg.generation.history_turns

    def rewrite(self, question: str, history: list[Turn]) -> str:
        if not history:  # defensive: nothing to resolve against, so the query is already standalone
            return question
        recent = history[-self._history_turns :] if self._history_turns else history
        user = (
            f"Conversation so far:\n{_format_history(recent)}\n\n"
            f"Latest user message: {question}\n\n"
            "Rewrite the latest user message as a standalone search query."
        )
        rewritten = self._client.complete(
            system=self._system,
            user=user,
            temperature=_REWRITE_TEMPERATURE,
            max_tokens=self._max_tokens,
        )
        return _clean(rewritten, fallback=question)


def build_query_rewriter(cfg: ResolvedConfig, client: LLMClient | None = None) -> QueryRewriter:
    """Load the configured rewrite prompt and wire the rewriter; builds the client if none given."""
    system_prompt = load_named_prompt(cfg.conversation.rewrite_prompt_variant)
    resolved_client = client if client is not None else build_llm_client(cfg.generation)
    return LLMQueryRewriter(cfg, resolved_client, system_prompt)
