"""CrawlIngestWorker: the real crawl→persist→ingest compose (Phase 9, FR-API-05 / FR-CRAWL-09).

Driven by fakes — a fake crawler, embedder, store, and a recording ingest_fn — so CI needs no
browser, Qdrant, or model. These pin what the worker guarantees:

  1. It is SYNC (a plain def), because the crawler uses Playwright's sync API which cannot run in
     an asyncio event loop.
  2. The raw crawl JSON is PERSISTED before ingest runs, and that file is re-readable by
     load_corpus — it is the demo's cached-ingest fallback.
  3. Per-crawl page/depth bounds reach the crawler and touch ONLY ingestion (index_key unchanged).
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

from chatbot.api.ingestion_service import CrawlIngestWorker, IngestionService
from chatbot.config.loader import load_config
from chatbot.ingestion.crawler.base import CrawledPage
from chatbot.ingestion.pipeline import IngestResult, load_corpus
from chatbot.store.fingerprint import IndexFingerprint

PAGES = [
    CrawledPage(url="https://cutpro.test/", title="Home",
                text="CutPro sells barber tools.", depth=0),
    CrawledPage(url="https://cutpro.test/pricing", title="Pricing",
                text="The Pro Kit is $199.", depth=1),
]


class FakeCrawler:
    backend = "playwright"

    def __init__(self, cfg: Any) -> None:
        self.cfg = cfg

    def crawl(self, root_url: str) -> list[CrawledPage]:
        return PAGES


class FakeEmbedder:
    dimensions = 384

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self.dimensions for _ in texts]


class FakeStore:
    def __init__(self) -> None:
        self.upserted = 0


def _worker(tmp_path: Path, ingest_fn: Any) -> CrawlIngestWorker:
    return CrawlIngestWorker(
        load_config("C0-baseline"),
        corpus_dir=tmp_path,
        crawler_factory=lambda ing_cfg: FakeCrawler(ing_cfg),
        embedder_factory=lambda emb_cfg: FakeEmbedder(),  # type: ignore[arg-type,return-value]
        store_factory=lambda store_cfg, dims: FakeStore(),  # type: ignore[arg-type,return-value]
        ingest_fn=ingest_fn,
    )


def test_worker_run_is_synchronous_not_async() -> None:
    # If this were `async def`, FastAPI would run it in the event loop and Playwright's sync API
    # would raise. It must be a plain def so BackgroundTasks runs it in the threadpool.
    assert not inspect.iscoroutinefunction(CrawlIngestWorker.run)
    assert not inspect.iscoroutinefunction(IngestionService.execute)


def test_crawl_json_is_persisted_before_ingest_and_is_reingestable(tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    def recording_ingest(cfg: Any, **kwargs: Any) -> IngestResult:
        manifest = kwargs["crawl_manifest"]
        # The JSON must already be on disk when ingest is called (persist-before-process).
        seen["manifest_exists_at_ingest"] = Path(manifest).exists()
        seen["pages"] = kwargs["pages"]
        fp = IndexFingerprint(
            domain_id=kwargs["domain_id"], index_key="k", config_id=cfg.id, chunking_hash="h",
            embedding_model="m", embedding_dimensions=384, crawl_manifest=manifest,
            chunk_count=len(kwargs["pages"]) * 3, ingested_at="now",
        )
        return IngestResult(
            fingerprint=fp, chunk_count=fp.chunk_count, by_type={"prose": fp.chunk_count}
        )

    outcome = _worker(tmp_path, recording_ingest).run(
        "cutpro", "https://cutpro.test", max_pages=None, max_depth=None
    )

    assert seen["manifest_exists_at_ingest"] is True  # FR-CRAWL-09: persisted before processing
    assert outcome.chunk_count == 6
    # The persisted file lands under <corpus_dir>/<domain_id>/ and is re-readable by load_corpus,
    # so the demo's cached fallback (ingest-from-JSON) has something to read.
    persisted = list((tmp_path / "cutpro").glob("crawl_*.json"))
    assert len(persisted) == 1
    reloaded = load_corpus(persisted[0])
    assert [p.url for p in reloaded] == [p.url for p in PAGES]


def test_bounds_reach_the_crawler_via_ingestion_only(tmp_path: Path) -> None:
    captured: dict[str, Any] = {}

    def capturing_crawler(ing_cfg: Any) -> FakeCrawler:
        captured["max_pages"] = ing_cfg.max_pages
        captured["max_depth"] = ing_cfg.max_depth
        return FakeCrawler(ing_cfg)

    def noop_ingest(cfg: Any, **kwargs: Any) -> IngestResult:
        # index_key must be unchanged by the bounds override (they touch only ingestion).
        captured["index_key"] = cfg.index_key()
        fp = IndexFingerprint(
            domain_id="cutpro", index_key=cfg.index_key(), config_id=cfg.id, chunking_hash="h",
            embedding_model="m", embedding_dimensions=384, crawl_manifest="", chunk_count=1,
            ingested_at="now",
        )
        return IngestResult(fingerprint=fp, chunk_count=1, by_type={})

    baseline_index_key = load_config("C0-baseline").index_key()
    worker = CrawlIngestWorker(
        load_config("C0-baseline"), corpus_dir=tmp_path,
        crawler_factory=capturing_crawler,
        embedder_factory=lambda c: FakeEmbedder(),  # type: ignore[arg-type,return-value]
        store_factory=lambda c, d: FakeStore(),  # type: ignore[arg-type,return-value]
        ingest_fn=noop_ingest,
    )
    worker.run("cutpro", "https://cutpro.test", max_pages=7, max_depth=1)

    assert (captured["max_pages"], captured["max_depth"]) == (7, 1)  # bounds threaded through
    assert captured["index_key"] == baseline_index_key  # index_key (RQ fingerprint) untouched
