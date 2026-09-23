"""Phase 9 — scrape-to-ingest orchestration and the key guard, before any implementation.

The "add a business" flow crawls a URL, ingests it, and registers the domain so it becomes
queryable. Three properties are pinned here:

  1. A successful crawl+ingest drives the registry to `ready` with the chunk count — the domain
     now exists for the business selector.
  2. A crawl/ingest that raises (a disallowed robots path, a dead site) drives the registry to
     `failed` with the error, never a half-created "ready" domain.
  3. The write endpoint refuses a request without the API key (FR-API-02) — crawling/ingesting on
     someone's behalf is not wide open.

All fakes — no live crawl, no Qdrant, no model. RED until Steps 1–3 build the registry, the
ingestion service, and the endpoint.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from chatbot.api.main import create_app
from chatbot.pipeline import ChatAnswer

CUTPRO = "cutpro"
CUTPRO_URL = "https://cutpro.test"


class FakeWorker:
    """Stands in for the real crawl+ingest worker: returns a canned outcome, or raises."""

    def __init__(self, *, chunk_count: int = 0, exc: Exception | None = None) -> None:
        self._chunk_count = chunk_count
        self._exc = exc
        self.calls: list[dict[str, Any]] = []

    def run(
        self, domain_id: str, root_url: str, *, max_pages: Any = None, max_depth: Any = None,
        corpus_path: Any = None,
    ) -> Any:
        from chatbot.api.ingestion_service import IngestOutcome

        self.calls.append({"domain_id": domain_id, "root_url": root_url,
                           "max_pages": max_pages, "max_depth": max_depth,
                           "corpus_path": corpus_path})
        if self._exc is not None:
            raise self._exc
        return IngestOutcome(chunk_count=self._chunk_count)


def _service(worker: FakeWorker) -> Any:
    from chatbot.api.ingestion_service import IngestionService
    from chatbot.store.business import InMemoryBusinessRegistry

    registry = InMemoryBusinessRegistry()
    return IngestionService(registry, worker), registry


def test_successful_crawl_ingest_marks_domain_ready() -> None:
    worker = FakeWorker(chunk_count=42)
    svc, registry = _service(worker)
    svc.add_business(CUTPRO, CUTPRO_URL, display_name="CutPro")
    svc.execute(CUTPRO, CUTPRO_URL, max_pages=10, max_depth=2)

    business = registry.get(CUTPRO)
    assert business.status == "ready"
    assert business.chunk_count == 42
    assert worker.calls[0]["max_pages"] == 10  # bounds threaded through to the worker


def test_worker_failure_marks_domain_failed_not_ready() -> None:
    worker = FakeWorker(exc=RuntimeError("robots.txt disallows the entry point"))
    svc, registry = _service(worker)
    svc.add_business(CUTPRO, CUTPRO_URL)
    svc.execute(CUTPRO, CUTPRO_URL, max_pages=10, max_depth=2)

    business = registry.get(CUTPRO)
    assert business.status == "failed"  # never a half-created 'ready' domain
    assert "robots" in business.error


class _FakePipeline:
    domain_id = "wyatt-edu"

    def answer(self, question: str, *, role: str | None = None) -> ChatAnswer:
        return ChatAnswer("x", [], True)


def _client_with_ingestion(token: str | None) -> tuple[TestClient, Any, FakeWorker]:
    worker = FakeWorker(chunk_count=1)
    svc, registry = _service(worker)
    app = create_app(
        pipeline=_FakePipeline(),  # type: ignore[arg-type]
        ingestion_service=svc, admin_token=token,
    )
    return TestClient(app), registry, worker


def test_crawl_endpoint_requires_the_api_key() -> None:
    body = {"domain_id": CUTPRO, "root_url": CUTPRO_URL}
    client, _, _ = _client_with_ingestion(token="s3cret")
    with client:
        no_key = client.post("/api/crawl/site", json=body)
        wrong = client.post("/api/crawl/site", headers={"X-API-Key": "nope"}, json=body)
        right = client.post("/api/crawl/site", headers={"X-API-Key": "s3cret"}, json=body)
    assert no_key.status_code in (401, 403)  # missing key refused
    assert wrong.status_code in (401, 403)  # wrong key refused
    assert right.status_code < 400  # correct key accepted (returns the pending job)


def test_post_returns_pending_then_the_background_task_runs_the_crawl() -> None:
    # The POST must not block on a minutes-long crawl: it returns `pending` immediately, and the
    # crawl+ingest runs off the request as a background task.
    client, registry, worker = _client_with_ingestion(token="s3cret")
    body = {"domain_id": CUTPRO, "root_url": CUTPRO_URL, "max_pages": 8}
    with client:
        resp = client.post("/api/crawl/site", headers={"X-API-Key": "s3cret"}, json=body)

    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"  # the response did NOT wait for the crawl result
    # The background task ran off the response path: the worker was invoked and the domain settled.
    assert worker.calls and worker.calls[0]["max_pages"] == 8
    assert registry.get(CUTPRO).status == "ready"


def test_ingestion_without_admin_token_fails_closed_with_503() -> None:
    # No token configured → the WRITE endpoint refuses (503), never wide open. Reads stay open.
    client, _, _ = _client_with_ingestion(token=None)
    with client:
        write = client.post(
            "/api/crawl/site", headers={"X-API-Key": "anything"},
            json={"domain_id": CUTPRO, "root_url": CUTPRO_URL},
        )
        read = client.get("/api/domains")
    assert write.status_code == 503  # fail closed
    assert "not configured" in write.json()["detail"]
    assert read.status_code == 200  # the selector still works without a token


def test_corpus_path_is_threaded_to_the_worker_for_cached_ingest() -> None:
    # The demo's cached fallback: POST with corpus_path → the worker ingests that saved JSON
    # instead of crawling live. Here we assert the endpoint threads it through.
    client, registry, worker = _client_with_ingestion(token="s3cret")
    cached = "data/corpora/cutpro/crawl_20260101T000000.json"
    with client:
        resp = client.post(
            "/api/crawl/site", headers={"X-API-Key": "s3cret"},
            json={"domain_id": CUTPRO, "root_url": CUTPRO_URL, "corpus_path": cached},
        )
    assert resp.json()["status"] == "pending"
    assert worker.calls[0]["corpus_path"] == cached  # cached path reached the worker
    assert registry.get(CUTPRO).status == "ready"


def test_status_and_domains_endpoints() -> None:
    client, _, _ = _client_with_ingestion(token="s3cret")
    with client:
        client.post(
            "/api/crawl/site", headers={"X-API-Key": "s3cret"},
            json={"domain_id": CUTPRO, "root_url": CUTPRO_URL, "display_name": "CutPro"},
        )
        status = client.get(f"/api/crawl/site/{CUTPRO}")
        domains = client.get("/api/domains")
        missing = client.get("/api/crawl/site/nope")

    assert status.status_code == 200 and status.json()["status"] == "ready"
    assert CUTPRO in {d["domain_id"] for d in domains.json()["domains"]}
    assert missing.status_code == 404
