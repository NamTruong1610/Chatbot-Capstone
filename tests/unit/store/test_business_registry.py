"""BusinessRegistry contract + fingerprint reconcile (Phase 9, FR-API-05).

The contract runs against both implementations — in-memory always (CI-safe) and Postgres only when
CHATBOT_POSTGRES_DSN points at a reachable database (else skipped, the Phase-8 / Playwright pattern)
— so the fake the API tests rely on behaves like the real store.

The reconcile test is the one the checkpoint calls for: domains ingested earlier via the CLI
(Wyatt, Austral) carry only an on-disk fingerprint, never a registry row; `reconcile_fingerprints`
must surface them as `ready` so GET /api/domains lists all three businesses, not just the
endpoint-added one.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

import pytest

from chatbot.store.business import (
    FAILED,
    INGESTING,
    PENDING,
    READY,
    Business,
    InMemoryBusinessRegistry,
    PostgresBusinessRegistry,
    reconcile_fingerprints,
)
from chatbot.store.fingerprint import IndexFingerprint, list_fingerprints, write_fingerprint

SCHEMA_SQL = (Path(__file__).resolve().parents[3] / "db" / "business_schema.sql").read_text()


def _postgres_available() -> bool:
    dsn = os.environ.get("CHATBOT_POSTGRES_DSN")
    if not dsn:
        return False
    try:
        PostgresBusinessRegistry(dsn).ensure_schema(SCHEMA_SQL)
        return True
    except Exception:
        return False


requires_postgres = pytest.mark.skipif(
    not _postgres_available(),
    reason="CHATBOT_POSTGRES_DSN unset or unreachable — Postgres contract tests skipped",
)


@pytest.fixture(params=["memory", pytest.param("postgres", marks=requires_postgres)])
def registry(request: Any) -> Any:
    if request.param == "memory":
        return InMemoryBusinessRegistry()
    pg = PostgresBusinessRegistry(os.environ["CHATBOT_POSTGRES_DSN"])
    pg.ensure_schema(SCHEMA_SQL)
    return pg  # unique domain ids per test keep a shared DB from cross-contaminating


def _domain() -> str:
    return f"cutpro-{uuid.uuid4().hex[:8]}"


def test_start_creates_a_pending_business(registry: Any) -> None:
    d = _domain()
    b = registry.start(d, root_url="https://cutpro.test", display_name="CutPro")
    assert (b.domain_id, b.display_name, b.root_url, b.status) == (
        d, "CutPro", "https://cutpro.test", PENDING,
    )
    assert registry.get(d).status == PENDING


def test_status_transitions_to_ready_with_chunk_count(registry: Any) -> None:
    d = _domain()
    registry.start(d, root_url="https://cutpro.test")
    registry.set_status(d, INGESTING)
    assert registry.get(d).status == INGESTING
    ready = registry.mark_ready(d, chunk_count=137)
    assert ready.status == READY
    assert ready.chunk_count == 137
    assert ready.error is None


def test_mark_failed_records_the_error_and_not_ready(registry: Any) -> None:
    d = _domain()
    registry.start(d, root_url="https://cutpro.test")
    failed = registry.mark_failed(d, error="robots.txt disallows the entry point")
    assert failed.status == FAILED
    assert "robots" in failed.error


def test_re_adding_resets_status_and_clears_error(registry: Any) -> None:
    d = _domain()
    registry.start(d, root_url="https://cutpro.test")
    registry.mark_failed(d, error="boom")
    again = registry.start(d, root_url="https://cutpro.test")  # a fresh add
    assert again.status == PENDING
    assert again.error is None


def test_list_all_returns_every_business(registry: Any) -> None:
    a, b = _domain(), _domain()
    registry.start(a, root_url="https://a.test")
    registry.start(b, root_url="https://b.test")
    listed = {x.domain_id for x in registry.list_all()}
    assert {a, b} <= listed


def test_get_unknown_domain_is_none(registry: Any) -> None:
    assert registry.get(_domain()) is None


# --- fingerprint reconcile (in-memory; the logic is store-agnostic) ---


def _fp(domain_id: str, chunk_count: int) -> IndexFingerprint:
    return IndexFingerprint(
        domain_id=domain_id, index_key="abc123", config_id="C0-baseline",
        chunking_hash="deadbeef", embedding_model="all-MiniLM-L6-v2", embedding_dimensions=384,
        crawl_manifest="", chunk_count=chunk_count, ingested_at="now",
    )


def test_reconcile_surfaces_cli_ingested_domains_as_ready() -> None:
    # Wyatt/Austral were ingested via the CLI — they have fingerprints but no registry row.
    registry = InMemoryBusinessRegistry()
    reconcile_fingerprints(registry, [_fp("wyatt-edu", 812), _fp("austral-eng", 349)])

    by_id = {b.domain_id: b for b in registry.list_all()}
    assert by_id["wyatt-edu"].status == READY and by_id["wyatt-edu"].chunk_count == 812
    assert by_id["austral-eng"].status == READY and by_id["austral-eng"].chunk_count == 349


def test_reconcile_does_not_overwrite_a_tracked_domain() -> None:
    # An endpoint-added domain mid-crawl must win over a stale fingerprint of the same id.
    registry = InMemoryBusinessRegistry()
    registry.start("cutpro", root_url="https://cutpro.test")
    registry.set_status("cutpro", INGESTING)
    reconcile_fingerprints(registry, [_fp("cutpro", 999)])
    tracked = registry.get("cutpro")
    assert tracked is not None and tracked.status == INGESTING  # not clobbered to ready


def test_list_fingerprints_reads_the_on_disk_registry(tmp_path: Path) -> None:
    write_fingerprint(_fp("wyatt-edu", 812), base_dir=tmp_path)
    write_fingerprint(_fp("austral-eng", 349), base_dir=tmp_path)
    domains = {fp.domain_id for fp in list_fingerprints(base_dir=tmp_path)}
    assert domains == {"wyatt-edu", "austral-eng"}


def test_reconcile_from_disk_end_to_end(tmp_path: Path) -> None:
    # The path GET /api/domains will use at startup: on-disk fingerprints → registry rows.
    write_fingerprint(_fp("wyatt-edu", 812), base_dir=tmp_path)
    registry = InMemoryBusinessRegistry()
    reconcile_fingerprints(registry, list_fingerprints(base_dir=tmp_path))
    wyatt = registry.get("wyatt-edu")
    assert isinstance(wyatt, Business)
    assert wyatt.status == READY
