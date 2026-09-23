"""FastAPI app factory: the demonstrable chatbot endpoints (FR-API-01/04).

The server is single-config, single-domain: it is built at startup for a chosen ``config_id``
(default C0-baseline — the arm RQ1 found pragmatic, so the chatbot ships the config the research
recommends) and ``domain_id``. Startup builds the pipeline once via the shared
``build_chat_pipeline``; the fingerprint guard there fails fast if the index is missing/mismatched,
so a broken deploy never serves wrong answers.

Conversation state (Phase 8) is threaded through a ``ConversationService``: a request with a
``session_id`` is multi-turn (history loaded, follow-up condensed, messages persisted); a request
without one is a stateless single-shot call, byte-for-byte what it always was. The route owns no
retrieve→generate logic — it shapes the request, delegates, and maps a scope violation to 403.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException

from chatbot.api.conversation import ConversationService
from chatbot.api.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationHistoryResponse,
    MessageOut,
)
from chatbot.config.loader import load_config
from chatbot.pipeline import ChatPipeline, build_chat_pipeline
from chatbot.store.conversation import (
    ConversationScopeError,
    ConversationStore,
    PostgresConversationStore,
    build_conversation_store,
)

DEFAULT_CONFIG_ID = "C0-baseline"
DEFAULT_DOMAIN_ID = "wyatt-edu"
_SCHEMA_PATH = Path(__file__).resolve().parents[3] / "db" / "conversation_schema.sql"


def create_app(
    *,
    config_id: str = DEFAULT_CONFIG_ID,
    domain_id: str = DEFAULT_DOMAIN_ID,
    pipeline: ChatPipeline | None = None,
    store: ConversationStore | None = None,
) -> FastAPI:
    """Build the app. ``pipeline``/``store`` are injectable so tests drive the endpoints with fakes
    (no store, no model, no Postgres); in production both are built at startup from ``config_id``.
    The real Postgres store is built only on the real path (``pipeline is None``), so an
    injected-pipeline test never requires a database."""
    cfg = load_config(config_id)
    state: dict[str, ConversationService | None] = {"service": None}
    if pipeline is not None:
        state["service"] = ConversationService(
            pipeline, store, domain_id=domain_id, history_turns=cfg.generation.history_turns
        )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if state["service"] is None:
            # Fingerprint guard runs here (fail fast at startup), not per request.
            built_pipeline = build_chat_pipeline(cfg, domain_id)
            built_store = store
            if built_store is None and cfg.conversation.enabled:
                built_store = build_conversation_store()  # reads CHATBOT_POSTGRES_DSN; fails loud
                if isinstance(built_store, PostgresConversationStore):
                    built_store.ensure_schema(_SCHEMA_PATH.read_text(encoding="utf-8"))
            state["service"] = ConversationService(
                built_pipeline, built_store, domain_id=domain_id,
                history_turns=cfg.generation.history_turns,
            )
        yield

    app = FastAPI(title="Chatbot (RAG) — RQ demo", lifespan=lifespan)

    def _service() -> ConversationService:
        service = state["service"]
        if service is None:  # pragma: no cover - lifespan builds it before requests are served
            raise HTTPException(status_code=503, detail="service not ready")
        return service

    @app.get("/health")
    def health() -> dict[str, str]:
        # FR-API-04: report the active configuration.
        return {"status": "ok", "config_id": cfg.id, "domain_id": domain_id}

    @app.post("/api/chat/message", response_model=ChatResponse, response_model_exclude_none=True)
    def chat_message(request: ChatRequest) -> ChatResponse:
        if request.domain_id is not None and request.domain_id != domain_id:
            raise HTTPException(
                status_code=400,
                detail=f"this server serves domain {domain_id!r}, not {request.domain_id!r}",
            )
        try:
            answer, session_id = _service().reply(
                request.message, session_id=request.session_id, role=request.role
            )
        except ConversationScopeError as exc:
            # Fail closed at the boundary: a session opened under a different (domain, role) is
            # refused, so a client cannot resume a conversation that is not theirs.
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        return ChatResponse(
            answer=answer.answer, sources=answer.sources, grounded=answer.grounded,
            session_id=session_id,
        )

    @app.get("/api/chat/conversation/{session_id}", response_model=ConversationHistoryResponse)
    def conversation_history(session_id: str) -> ConversationHistoryResponse:
        messages = _service().list_messages(session_id)
        return ConversationHistoryResponse(
            session_id=session_id,
            messages=[
                MessageOut(
                    turn_index=m.turn_index, sender=m.sender, content=m.content,
                    grounded=m.grounded, sources=m.sources, search_query=m.search_query,
                )
                for m in messages
            ],
        )

    return app
