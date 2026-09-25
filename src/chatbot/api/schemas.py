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


class ConversationSummaryOut(BaseModel):
    """A row in the conversation browser (FR-API-07). Carries its scope so the UI can resume it."""

    session_id: str
    domain_id: str
    role: str
    title: str
    preview: str
    updated_at: str
    message_count: int


class ConversationsResponse(BaseModel):
    conversations: list[ConversationSummaryOut]


class CrawlSiteRequest(BaseModel):
    """Body for POST /api/crawl/site (FR-API-05). Optional bounds keep a demo crawl fast."""

    domain_id: str = Field(min_length=1)
    root_url: str = Field(min_length=1)
    display_name: str | None = None
    max_pages: int | None = Field(default=None, ge=1)
    max_depth: int | None = Field(default=None, ge=0)
    # Cached fallback: ingest this saved crawl JSON instead of crawling live (the demo insurance).
    corpus_path: str | None = None


class BusinessOut(BaseModel):
    """A registered business and its ingest state — the POST/status response and selector entry."""

    domain_id: str
    display_name: str
    root_url: str
    status: str
    chunk_count: int
    error: str | None = None


class DomainsResponse(BaseModel):
    domains: list[BusinessOut]


class PrivateNoteRequest(BaseModel):
    """Body for POST /api/ingest/private (FR-API-06): staff-authored private text, no crawl."""

    domain_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    text: str = Field(min_length=1)


class PrivateNoteResponse(BaseModel):
    domain_id: str
    title: str
    chunks_added: int
    access_level: str = "private"
