"""Scrape-to-ingest orchestration (Phase 9, FR-API-05): crawl a URL, ingest it, register the domain.

Two pieces:

- ``IngestionService`` owns the registry status lifecycle. ``add_business`` records the pending
  domain (the endpoint returns immediately); ``execute`` is the background body that runs the
  worker and drives the registry to ``ready`` or ``failed`` — never a half-created ``ready`` domain.
- ``CrawlIngestWorker`` does the heavy work by composing the existing parts: ``build_crawler`` →
  crawl → **persist the crawl JSON** (FR-CRAWL-09) → ``build_embedder`` + ``VectorStore`` →
  ``ingest``. Nothing in the crawler/ingest/store internals changes; this is a compose over them.

``execute`` and ``CrawlIngestWorker.run`` are deliberately **plain ``def`` (synchronous)**. The
crawler uses Playwright's sync API, which cannot run inside an asyncio event loop — so the endpoint
schedules this via FastAPI ``BackgroundTasks`` for a *sync* function, which runs it in the
threadpool, off the loop. An ``async def`` worker would crash Playwright.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from chatbot.config.schema import EmbeddingConfig, IngestionConfig, ResolvedConfig, StoreConfig
from chatbot.ingestion.crawler.base import CrawledPage, Crawler, build_crawler
from chatbot.ingestion.pipeline import IngestResult, ingest, load_corpus
from chatbot.store.business import CRAWLING, Business, BusinessRegistry
from chatbot.store.embedder import TextEmbedder, build_embedder
from chatbot.store.vector import VectorStore

# Raw crawl output lands here before any processing (FR-CRAWL-09), one dir per domain. This same
# JSON is the demo's cached fallback: if a live crawl is slow/down on stage, the endpoint can
# re-ingest it via load_corpus without touching the network.
DEFAULT_CORPUS_DIR = Path("data/corpora")


@dataclass(frozen=True)
class IngestOutcome:
    """What one crawl+ingest produced."""

    chunk_count: int
    crawl_manifest: str = ""


@runtime_checkable
class IngestWorker(Protocol):
    """The heavy crawl+ingest step. Faked in tests so CI needs no browser, Qdrant, or model."""

    def run(
        self,
        domain_id: str,
        root_url: str,
        *,
        max_pages: int | None,
        max_depth: int | None,
        corpus_path: str | None = None,
    ) -> IngestOutcome: ...


class IngestionService:
    """Registry status lifecycle around an injected worker. Stateless; safe to build per app."""

    def __init__(self, registry: BusinessRegistry, worker: IngestWorker) -> None:
        self._registry = registry
        self._worker = worker

    def add_business(
        self,
        domain_id: str,
        root_url: str,
        *,
        display_name: str | None = None,
    ) -> Business:
        """Record the domain as pending and return it — the endpoint responds with this at once."""
        return self._registry.start(domain_id, root_url=root_url, display_name=display_name)

    def execute(
        self,
        domain_id: str,
        root_url: str,
        *,
        max_pages: int | None = None,
        max_depth: int | None = None,
        corpus_path: str | None = None,
    ) -> Business:
        """Run the crawl+ingest and settle the registry. SYNC on purpose (Playwright, see module).

        Any failure — a disallowed robots path, a dead site, an empty crawl — is caught and recorded
        as ``failed`` with the reason, so a failed add never leaves a queryable-looking domain.
        ``corpus_path`` ingests from a previously-saved crawl JSON instead of crawling live — the
        demo's cached fallback when a live crawl is slow or unavailable.
        """
        self._registry.set_status(domain_id, CRAWLING)
        try:
            outcome = self._worker.run(
                domain_id, root_url, max_pages=max_pages, max_depth=max_depth,
                corpus_path=corpus_path,
            )
        except Exception as exc:  # noqa: BLE001 - the reason is surfaced to the caller via the row
            return self._registry.mark_failed(domain_id, error=str(exc))
        return self._registry.mark_ready(domain_id, chunk_count=outcome.chunk_count)

    def get_status(self, domain_id: str) -> Business | None:
        """The current state of one business (backs the status endpoint)."""
        return self._registry.get(domain_id)

    def list_businesses(self) -> list[Business]:
        """Every registered business (backs GET /api/domains and the selector)."""
        return self._registry.list_all()


def _default_store(store_cfg: StoreConfig, dimensions: int) -> VectorStore:
    return VectorStore(store_cfg, dimensions=dimensions)


class CrawlIngestWorker:
    """The real worker: build_crawler → crawl → persist JSON → embed → store → ingest.

    Collaborators are injectable factories so tests drive it with fakes (no browser, Qdrant, or
    model). The robots/blocklist rules are the crawler's own and are NOT bypassable here — an
    admin crawl is a guest on someone's site exactly like any other (FR-CRAWL-05/07).
    """

    def __init__(
        self,
        cfg: ResolvedConfig,
        *,
        corpus_dir: Path = DEFAULT_CORPUS_DIR,
        crawler_factory: Callable[[IngestionConfig], Crawler] = build_crawler,
        embedder_factory: Callable[[EmbeddingConfig], TextEmbedder] = build_embedder,
        store_factory: Callable[[StoreConfig, int], VectorStore] = _default_store,
        ingest_fn: Callable[..., IngestResult] = ingest,
    ) -> None:
        self._cfg = cfg
        self._corpus_dir = corpus_dir
        self._crawler_factory = crawler_factory
        self._embedder_factory = embedder_factory
        self._store_factory = store_factory
        self._ingest_fn = ingest_fn

    def _cfg_with_bounds(self, max_pages: int | None, max_depth: int | None) -> ResolvedConfig:
        """Apply per-crawl page/depth bounds. These touch ONLY ``ingestion`` — not chunking or
        embedding — so ``index_key`` and every RQ fingerprint stay byte-identical (flag 3)."""
        overrides = {
            k: v
            for k, v in (("max_pages", max_pages), ("max_depth", max_depth))
            if v is not None
        }
        if not overrides:
            return self._cfg
        ingestion = self._cfg.ingestion.model_copy(update=overrides)
        return self._cfg.model_copy(update={"ingestion": ingestion})

    def _persist_crawl(
        self, domain_id: str, root_url: str, backend: str, pages: list[CrawledPage]
    ) -> Path:
        """Write raw crawl output BEFORE any processing (FR-CRAWL-09). The corpus must survive the
        site changing, and this file is the demo's cached-ingest fallback (re-readable by
        ``load_corpus``, which accepts ``{"pages": [...]}``)."""
        out_dir = self._corpus_dir / domain_id
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        path = out_dir / f"crawl_{stamp}.json"
        manifest = {
            "domain_id": domain_id,
            "root_url": root_url,
            "backend": backend,
            "pages_fetched": len(pages),
            "pages": [asdict(page) for page in pages],
        }
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def run(
        self,
        domain_id: str,
        root_url: str,
        *,
        max_pages: int | None,
        max_depth: int | None,
        corpus_path: str | None = None,
    ) -> IngestOutcome:
        """SYNC (Playwright). Crawl, persist the JSON, then ingest — or, with ``corpus_path``, skip
        the live crawl and ingest a previously-saved crawl JSON (the demo's cached fallback)."""
        run_cfg = self._cfg_with_bounds(max_pages, max_depth)
        if corpus_path is not None:
            # Cached path: no network, no browser. The saved file IS the manifest; it was persisted
            # (FR-CRAWL-09) on the live crawl that produced it, so nothing is re-written here.
            pages = load_corpus(Path(corpus_path))
            manifest = corpus_path
        else:
            crawler = self._crawler_factory(run_cfg.ingestion)
            pages = crawler.crawl(root_url)
            manifest = str(
                self._persist_crawl(
                    domain_id, root_url, getattr(crawler, "backend", "unknown"), pages
                )
            )
        embedder = self._embedder_factory(run_cfg.embedding)
        store = self._store_factory(run_cfg.store, embedder.dimensions)
        result = self._ingest_fn(
            run_cfg,
            domain_id=domain_id,
            root_url=root_url,
            pages=pages,
            store=store,
            embedder=embedder,
            crawl_manifest=manifest,
        )
        return IngestOutcome(chunk_count=result.chunk_count, crawl_manifest=manifest)
