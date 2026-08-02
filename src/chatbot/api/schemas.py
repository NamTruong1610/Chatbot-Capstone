"""Request/response models for the chat endpoint (FR-API-01, minimal subset).

Body is ``{message, role?, domain_id?}``; response is ``{answer, sources, grounded}``. The
``grounded`` flag is the whole point of strict-grounded generation, so it is first-class here.
Redis sessions / user_id (FR-API-03) are deferred.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    role: str | None = None
    domain_id: str | None = None


class ChatResponse(BaseModel):
    answer: str
    sources: list[str]
    grounded: bool
