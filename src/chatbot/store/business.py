"""Business (domain) registry (Phase 9, FR-API-05): which businesses exist and their ingest state.

Domains are now created at runtime (the scrape-to-ingest endpoint), not only the two pre-ingested
via the CLI, so the app needs a place to list them — the future business selector reads it. The
same row carries the async ingest status (pending → crawling → ingesting → ready | failed), so a
long crawl's progress is durable and pollable without a separate jobs table (demo-simple).

Two implementations behind one Protocol — in-memory (CI/tests) and Postgres (psycopg 3, lazy) —
exactly the Phase-8 ConversationStore pattern, reusing the same Postgres. The store imports
``config`` only (docs/04 layering); ``reconcile_fingerprints`` bridges the on-disk fingerprint
registry into it so CLI-ingested domains (Wyatt, Austral) appear alongside endpoint-added ones.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from chatbot.store.fingerprint import IndexFingerprint

# Status values, doubling as the async ingest-job state.
PENDING = "pending"
CRAWLING = "crawling"
INGESTING = "ingesting"
READY = "ready"
FAILED = "failed"

_DSN_ENV = "CHATBOT_POSTGRES_DSN"


class BusinessError(RuntimeError):
    """The registry cannot be reached or configured."""


@dataclass(frozen=True)
class Business:
    """A registered domain and its current ingest state."""

    domain_id: str
    display_name: str
    root_url: str
    status: str
    chunk_count: int = 0
    error: str | None = None


@runtime_checkable
class BusinessRegistry(Protocol):
    """List/track businesses. Implementations: in-memory (tests) and Postgres."""

    def start(self, domain_id: str, *, root_url: str, display_name: str | None = None) -> Business:
        """Create-or-reset the domain to `pending` (a re-add clears prior status/error)."""
        ...

    def set_status(self, domain_id: str, status: str) -> Business:
        """Advance an in-progress ingest (crawling / ingesting)."""
        ...

    def mark_ready(self, domain_id: str, *, chunk_count: int) -> Business:
        """The domain is queryable: `ready` with its chunk count."""
        ...

    def mark_failed(self, domain_id: str, *, error: str) -> Business:
        """The ingest failed: `failed` with the reason — never a half-created `ready` domain."""
        ...

    def get(self, domain_id: str) -> Business | None: ...

    def list_all(self) -> list[Business]:
        """Every registered business, for the selector / GET /api/domains."""
        ...


def reconcile_fingerprints(
    registry: BusinessRegistry, fingerprints: Iterable[IndexFingerprint]
) -> None:
    """Surface fingerprint-backed domains (CLI-ingested, e.g. Wyatt/Austral) into the registry as
    `ready`, so the selector lists every queryable business — not only endpoint-added ones.

    A domain the registry already tracks is left as-is: an in-progress add or an endpoint-created
    row wins over the on-disk fingerprint. The fingerprint carries no root_url/display_name, so
    those default to empty / the domain id; the point is only that the domain shows up and is
    queryable, with its real chunk count.
    """
    known = {b.domain_id for b in registry.list_all()}
    for fp in fingerprints:
        if fp.domain_id in known:
            continue
        registry.start(fp.domain_id, root_url="", display_name=fp.domain_id)
        registry.mark_ready(fp.domain_id, chunk_count=fp.chunk_count)


class InMemoryBusinessRegistry:
    """Process-local registry for CI and tests. Same contract as Postgres, no persistence."""

    def __init__(self) -> None:
        self._rows: dict[str, Business] = {}

    def start(self, domain_id: str, *, root_url: str, display_name: str | None = None) -> Business:
        business = Business(
            domain_id=domain_id,
            display_name=display_name or domain_id,
            root_url=root_url,
            status=PENDING,
            chunk_count=0,
            error=None,
        )
        self._rows[domain_id] = business
        return business

    def _update(self, domain_id: str, **changes: Any) -> Business:
        current = self._rows.get(domain_id)
        if current is None:
            raise BusinessError(f"no such business {domain_id!r}; start it first")
        from dataclasses import replace

        updated = replace(current, **changes)
        self._rows[domain_id] = updated
        return updated

    def set_status(self, domain_id: str, status: str) -> Business:
        return self._update(domain_id, status=status)

    def mark_ready(self, domain_id: str, *, chunk_count: int) -> Business:
        return self._update(domain_id, status=READY, chunk_count=chunk_count, error=None)

    def mark_failed(self, domain_id: str, *, error: str) -> Business:
        return self._update(domain_id, status=FAILED, error=error)

    def get(self, domain_id: str) -> Business | None:
        return self._rows.get(domain_id)

    def list_all(self) -> list[Business]:
        return sorted(self._rows.values(), key=lambda b: b.domain_id)


class PostgresBusinessRegistry:
    """Postgres-backed registry via psycopg 3. Plain SQL, lazy import (one table)."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def _connect(self) -> Any:
        import psycopg

        return psycopg.connect(self._dsn)

    def ensure_schema(self, schema_sql: str) -> None:
        with self._connect() as conn:
            conn.execute(schema_sql)

    def start(self, domain_id: str, *, root_url: str, display_name: str | None = None) -> Business:
        name = display_name or domain_id
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO businesses (domain_id, display_name, root_url, status) "
                "VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (domain_id) DO UPDATE SET display_name = EXCLUDED.display_name, "
                "root_url = EXCLUDED.root_url, status = EXCLUDED.status, chunk_count = 0, "
                "error = NULL, updated_at = now()",
                (domain_id, name, root_url, PENDING),
            )
        return Business(domain_id, name, root_url, PENDING, 0, None)

    def _update(self, domain_id: str, sets: str, params: tuple[Any, ...]) -> Business:
        with self._connect() as conn:
            row = conn.execute(
                f"UPDATE businesses SET {sets}, updated_at = now() WHERE domain_id = %s "
                "RETURNING domain_id, display_name, root_url, status, chunk_count, error",
                (*params, domain_id),
            ).fetchone()
        if row is None:
            raise BusinessError(f"no such business {domain_id!r}; start it first")
        return Business(row[0], row[1], row[2], row[3], row[4], row[5])

    def set_status(self, domain_id: str, status: str) -> Business:
        return self._update(domain_id, "status = %s", (status,))

    def mark_ready(self, domain_id: str, *, chunk_count: int) -> Business:
        return self._update(
            domain_id, "status = %s, chunk_count = %s, error = NULL", (READY, chunk_count)
        )

    def mark_failed(self, domain_id: str, *, error: str) -> Business:
        return self._update(domain_id, "status = %s, error = %s", (FAILED, error))

    def get(self, domain_id: str) -> Business | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT domain_id, display_name, root_url, status, chunk_count, error "
                "FROM businesses WHERE domain_id = %s",
                (domain_id,),
            ).fetchone()
        return None if row is None else Business(row[0], row[1], row[2], row[3], row[4], row[5])

    def list_all(self) -> list[Business]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT domain_id, display_name, root_url, status, chunk_count, error "
                "FROM businesses ORDER BY domain_id ASC"
            ).fetchall()
        return [Business(r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows]


def build_business_registry(dsn: str | None = None) -> BusinessRegistry:
    """Build the Postgres registry from ``dsn`` or ``CHATBOT_POSTGRES_DSN``; fail loud if unset.

    Infrastructure, read from the environment (decision 4) — not an experiment parameter.
    """
    resolved = dsn or os.environ.get(_DSN_ENV)
    if not resolved:
        raise BusinessError(
            f"no Postgres DSN: set ${_DSN_ENV} (e.g. postgresql://chatbot@localhost:5432/chatbot)"
        )
    return PostgresBusinessRegistry(resolved)
