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

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException

from chatbot.api.conversation import ConversationService
from chatbot.api.ingestion_service import CrawlIngestWorker, IngestionService
from chatbot.api.pipeline_registry import PipelineRegistry
from chatbot.api.schemas import (
    BusinessOut,
    ChatRequest,
    ChatResponse,
    ConversationHistoryResponse,
    CrawlSiteRequest,
    DomainsResponse,
    MessageOut,
)
from chatbot.config.loader import load_config
from chatbot.pipeline import ChatPipeline, IndexNotReadyError, build_chat_pipeline
from chatbot.store.business import (
    Business,
    PostgresBusinessRegistry,
    build_business_registry,
    reconcile_fingerprints,
)
from chatbot.store.conversation import (
    ConversationScopeError,
    ConversationStore,
    PostgresConversationStore,
    build_conversation_store,
)
from chatbot.store.fingerprint import list_fingerprints

DEFAULT_CONFIG_ID = "C0-baseline"
DEFAULT_DOMAIN_ID = "wyatt-edu"
_ADMIN_TOKEN_ENV = "CHATBOT_ADMIN_TOKEN"
_DB_DIR = Path(__file__).resolve().parents[3] / "db"
_SCHEMA_PATH = _DB_DIR / "conversation_schema.sql"
_BUSINESS_SCHEMA_PATH = _DB_DIR / "business_schema.sql"


def create_app(
    *,
    config_id: str = DEFAULT_CONFIG_ID,
    domain_id: str = DEFAULT_DOMAIN_ID,
    pipeline: ChatPipeline | None = None,
    store: ConversationStore | None = None,
    ingestion_service: IngestionService | None = None,
    pipeline_registry: PipelineRegistry | None = None,
    admin_token: str | None = None,
) -> FastAPI:
    """Build the app. ``pipeline``/``store``/``ingestion_service`` are injectable so tests drive the
    endpoints with fakes (no store, no model, no Postgres); in production they are built at startup
    from ``config_id``. The real Postgres-backed services are built only on the real path
    (``pipeline is None``), so an injected-pipeline test never requires a database.

    ``admin_token`` guards the write (crawl/ingest) endpoints (FR-API-02); it defaults to
    ``$CHATBOT_ADMIN_TOKEN``. When neither is set the write endpoints fail closed with 503 —
    ingestion is never wide open by default."""
    cfg = load_config(config_id)
    resolved_admin_token = admin_token if admin_token is not None else os.environ.get(
        _ADMIN_TOKEN_ENV
    )
    state: dict[str, ConversationService | None] = {"service": None}
    ingestion_state: dict[str, IngestionService | None] = {"service": ingestion_service}
    # Multi-domain routing (Phase 9): the default domain is served by state["service"] exactly as
    # before; other domains are served through a PipelineRegistry, each pipeline built once and
    # cached, wrapped in a per-domain ConversationService sharing the one store.
    routing: dict[str, Any] = {"provider": pipeline_registry, "store": store, "cache": {}}
    if pipeline is not None:
        state["service"] = ConversationService(
            pipeline, store, domain_id=domain_id, history_turns=cfg.generation.history_turns
        )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # Only the real path (no injected pipeline) builds the Postgres-backed services at startup;
        # an injected-pipeline test never reaches here, so it never requires a database.
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
            # Non-default domains (businesses added at runtime) are served through the registry,
            # sharing the one conversation store. The default pipeline built above is not re-built.
            routing["store"] = built_store
            routing["provider"] = PipelineRegistry(cfg)
            if ingestion_state["service"] is None:
                # Build the registry (same Postgres) and reconcile CLI-ingested domains
                # (Wyatt/Austral) so GET /api/domains lists every queryable business, not only
                # endpoint-added ones.
                registry = build_business_registry()
                if isinstance(registry, PostgresBusinessRegistry):
                    registry.ensure_schema(_BUSINESS_SCHEMA_PATH.read_text(encoding="utf-8"))
                reconcile_fingerprints(registry, list_fingerprints())
                ingestion_state["service"] = IngestionService(registry, CrawlIngestWorker(cfg))
        yield

    app = FastAPI(title="Chatbot (RAG) — RQ demo", lifespan=lifespan)

    def _service() -> ConversationService:
        service = state["service"]
        if service is None:  # pragma: no cover - lifespan builds it before requests are served
            raise HTTPException(status_code=503, detail="service not ready")
        return service

    def _ingestion() -> IngestionService:
        service = ingestion_state["service"]
        if service is None:  # pragma: no cover - lifespan builds it before requests are served
            raise HTTPException(status_code=503, detail="ingestion not available")
        return service

    def _conversation_for(target_domain: str) -> ConversationService:
        """The ConversationService for one domain. The default domain uses the pre-built service
        (the single-domain path, unchanged); other domains are built once via the registry and
        cached. An uningested domain raises IndexNotReadyError → 404; a single-domain server (no
        registry) rejects any non-default domain → 400."""
        if target_domain == domain_id:
            return _service()
        provider: PipelineRegistry | None = routing["provider"]
        if provider is None:
            raise HTTPException(
                status_code=400,
                detail=f"this server serves domain {domain_id!r}, not {target_domain!r}",
            )
        cache: dict[str, ConversationService] = routing["cache"]
        cached = cache.get(target_domain)
        if cached is not None:
            return cached  # second request to a domain reuses the built pipeline — no rebuild
        try:
            pipe = provider.get(target_domain)  # fingerprint guard fires here on first access
        except IndexNotReadyError as exc:
            raise HTTPException(
                status_code=404,
                detail=f"domain {target_domain!r} is not ingested/ready: {exc}",
            ) from exc
        conversation = ConversationService(
            pipe, routing["store"], domain_id=target_domain,
            history_turns=cfg.generation.history_turns,
        )
        cache[target_domain] = conversation
        return conversation

    def _require_admin(x_api_key: str | None) -> None:
        # Fail closed: with no token configured the write endpoints are refused, not wide open.
        if resolved_admin_token is None:
            raise HTTPException(
                status_code=503,
                detail=f"ingestion is not configured (set ${_ADMIN_TOKEN_ENV})",
            )
        if not x_api_key or x_api_key != resolved_admin_token:
            raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")

    def _business_out(business: Business) -> BusinessOut:
        return BusinessOut(
            domain_id=business.domain_id, display_name=business.display_name,
            root_url=business.root_url, status=business.status,
            chunk_count=business.chunk_count, error=business.error,
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        # FR-API-04: report the active configuration.
        return {"status": "ok", "config_id": cfg.id, "domain_id": domain_id}

    @app.post("/api/chat/message", response_model=ChatResponse, response_model_exclude_none=True)
    def chat_message(request: ChatRequest) -> ChatResponse:
        target_domain = request.domain_id or domain_id
        conversation = _conversation_for(target_domain)  # 400 (unserved) / 404 (not ingested)
        try:
            answer, session_id = conversation.reply(
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

    @app.post("/api/crawl/site", response_model=BusinessOut)
    def crawl_site(
        request: CrawlSiteRequest,
        background_tasks: BackgroundTasks,
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    ) -> BusinessOut:
        # Guard first (FR-API-02), then record the domain as pending and hand the long crawl+ingest
        # to a background task so the request returns at once — it never blocks on the crawl.
        _require_admin(x_api_key)
        svc = _ingestion()
        business = svc.add_business(
            request.domain_id, request.root_url, display_name=request.display_name
        )
        background_tasks.add_task(
            svc.execute, request.domain_id, request.root_url,
            max_pages=request.max_pages, max_depth=request.max_depth,
            corpus_path=request.corpus_path,
        )
        return _business_out(business)

    @app.get("/api/crawl/site/{domain_id}", response_model=BusinessOut)
    def crawl_status(domain_id: str) -> BusinessOut:
        business = _ingestion().get_status(domain_id)
        if business is None:
            raise HTTPException(status_code=404, detail=f"no such business {domain_id!r}")
        return _business_out(business)

    @app.get("/api/domains", response_model=DomainsResponse)
    def list_domains() -> DomainsResponse:
        # Read-only: the business selector needs this without a key.
        return DomainsResponse(
            domains=[_business_out(b) for b in _ingestion().list_businesses()]
        )

    return app
