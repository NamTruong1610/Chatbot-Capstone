"""FastAPI app factory: the demonstrable chatbot endpoint (FR-API-01/04).

The server is single-config, single-domain: it is built at startup for a chosen ``config_id``
(default C0-baseline — the arm RQ1 found pragmatic, so the chatbot ships the config the research
recommends) and ``domain_id``. Startup builds the pipeline once via the shared
``build_chat_pipeline``; the fingerprint guard there fails fast if the index is missing/mismatched,
so a broken deploy never serves wrong answers. Each request just calls ``pipeline.answer`` — no
retrieval or generation logic lives in the route.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from chatbot.api.schemas import ChatRequest, ChatResponse
from chatbot.config.loader import load_config
from chatbot.pipeline import ChatPipeline, build_chat_pipeline

DEFAULT_CONFIG_ID = "C0-baseline"
DEFAULT_DOMAIN_ID = "wyatt-edu"


def create_app(
    *,
    config_id: str = DEFAULT_CONFIG_ID,
    domain_id: str = DEFAULT_DOMAIN_ID,
    pipeline: ChatPipeline | None = None,
) -> FastAPI:
    """Build the app. ``pipeline`` is injectable so tests drive the endpoint with a fake (no
    store, no model, no Ollama); in production it is built at startup from ``config_id``."""
    cfg = load_config(config_id)
    state: dict[str, ChatPipeline | None] = {"pipeline": pipeline}

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if state["pipeline"] is None:
            # Fingerprint guard runs here (fail fast at startup), not per request.
            state["pipeline"] = build_chat_pipeline(cfg, domain_id)
        yield

    app = FastAPI(title="Chatbot (RAG) — RQ demo", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        # FR-API-04: report the active configuration.
        return {"status": "ok", "config_id": cfg.id, "domain_id": domain_id}

    @app.post("/api/chat/message", response_model=ChatResponse)
    def chat_message(request: ChatRequest) -> ChatResponse:
        pipe = state["pipeline"]
        if pipe is None:  # pragma: no cover - lifespan builds it before requests are served
            raise HTTPException(status_code=503, detail="pipeline not ready")
        if request.domain_id is not None and request.domain_id != pipe.domain_id:
            raise HTTPException(
                status_code=400,
                detail=f"this server serves domain {pipe.domain_id!r}, not {request.domain_id!r}",
            )
        result = pipe.answer(request.message, role=request.role)
        return ChatResponse(
            answer=result.answer, sources=result.sources, grounded=result.grounded
        )

    return app
