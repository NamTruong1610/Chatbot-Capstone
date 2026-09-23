"""Conversation orchestration: load history → answer → persist (Phase 8, FR-API-01/03).

This is the layer that turns a stateless retrieve→generate pipeline into a multi-turn chat. It sits
in ``api`` (which may import everything) so the pipeline and the store both stay pure: the pipeline
never touches Postgres, the store never imports generation. The one bridge — the store's
``Exchange`` mapped to ``generation.Turn`` — lives here.

Two paths:

- **Stateless** (no ``session_id``, or no store configured): call the pipeline exactly as the
  single-shot endpoint always did — no history, nothing persisted. This is what keeps existing
  callers byte-for-byte unchanged.
- **Stateful** (a ``session_id``): open the conversation under its fixed ``(domain, role)`` scope
  (fail closed), load the recent history, condense-and-answer with it, then persist both the user
  message and the assistant reply (with its grounding, sources, and the rewritten query).
"""

from __future__ import annotations

from chatbot.generation.history import Turn
from chatbot.pipeline import ChatAnswer, ChatPipeline
from chatbot.store.conversation import (
    ASSISTANT,
    USER,
    ConversationStore,
    Message,
)

_DEFAULT_ROLE = "customer"  # an anonymous request is the public role — matches ChatPipeline


class ConversationService:
    """Wires a ChatPipeline to a ConversationStore. Stateless when there is no session or store."""

    def __init__(
        self,
        pipeline: ChatPipeline,
        store: ConversationStore | None,
        *,
        domain_id: str,
        history_turns: int,
    ) -> None:
        self._pipeline = pipeline
        self._store = store
        self._domain = domain_id
        self._history_turns = history_turns

    def reply(
        self, message: str, *, session_id: str | None, role: str | None
    ) -> tuple[ChatAnswer, str | None]:
        """Answer ``message``; persist it under ``session_id`` when one is given and a store exists.

        Returns the answer and the session id to echo (None when the turn was stateless). A scope
        violation raised by the store propagates — the route maps it to an HTTP error, so the
        fail-closed guarantee holds at the boundary a client actually hits.
        """
        if session_id is None or self._store is None:
            return self._pipeline.answer(message, role=role), None

        # Resolve the role once so the conversation's scope and the retrieval role are identical:
        # the stored role governs BOTH what may be retrieved and who may resume the conversation.
        effective_role = role or _DEFAULT_ROLE
        self._store.open_conversation(session_id, self._domain, effective_role)

        exchanges = self._store.recent_exchanges(session_id, limit_turns=self._history_turns)
        history = [Turn(user=e.user, assistant=e.assistant) for e in exchanges]

        answer = self._pipeline.answer(message, role=effective_role, history=history)

        self._store.append_message(session_id, sender=USER, content=message)
        self._store.append_message(
            session_id,
            sender=ASSISTANT,
            content=answer.answer,
            grounded=answer.grounded,
            sources=answer.sources,
            search_query=answer.search_query,
        )
        return answer, session_id

    def list_messages(self, session_id: str) -> list[Message]:
        """The full message log for a conversation, or empty when no store is configured."""
        if self._store is None:
            return []
        return self._store.list_messages(session_id)
