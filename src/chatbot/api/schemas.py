"""Request/response models for the chat endpoints (FR-API-01).

Chat body is ``{message, role?, domain_id?, session_id?, user_id?}``; the response is
``{answer, sources, grounded, session_id?}``. ``session_id`` is the conversation id: absent on a
stateless single-shot request (and then excluded from the response, so an existing caller sees the
exact ``{answer, sources, grounded}`` it always did), echoed when the request is part of a
conversation. The ``grounded`` flag is the whole point of strict-grounded generation, so it stays
first-class. ``user_id`` is accepted per FR-API-01 but not yet used for scoping (conversations are
scoped by session_id + domain + role).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    role: str | None = None
    domain_id: str | None = None
    # Conversation id. Omit for a stateless single-shot request (backward-compatible: no history,
    # nothing persisted). Provide it to make the turn part of a conversation — history is loaded,
    # the follow-up is condensed, and both messages are persisted under this id.
    session_id: str | None = None
    user_id: str | None = None


class ChatResponse(BaseModel):
    answer: str
    sources: list[str]
    grounded: bool
    # Echoed only for a stateful turn; None (and excluded from the JSON) for a stateless one.
    session_id: str | None = None


class MessageOut(BaseModel):
    """One stored message, as returned by the fetch-a-conversation endpoint."""

    turn_index: int
    sender: str
    content: str
    grounded: bool | None = None
    sources: list[str] = Field(default_factory=list)
    search_query: str | None = None


class ConversationHistoryResponse(BaseModel):
    session_id: str
    messages: list[MessageOut]
