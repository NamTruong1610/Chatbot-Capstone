-- Business (domain) registry (Phase 9, FR-API-05).
--
-- One row per business/domain the app knows about — those added through the scrape endpoint
-- and, reconciled at startup, those ingested earlier via the CLI (Wyatt, Austral). The future
-- business selector reads this to list what can be queried. `status` doubles as the async
-- ingest job state, so a long crawl's progress is durable and pollable. Idempotent
-- (IF NOT EXISTS), run at startup like the conversation schema.

CREATE TABLE IF NOT EXISTS businesses (
    domain_id    TEXT PRIMARY KEY,
    display_name TEXT        NOT NULL DEFAULT '',
    root_url     TEXT        NOT NULL DEFAULT '',
    -- pending | crawling | ingesting | ready | failed
    status       TEXT        NOT NULL,
    chunk_count  INTEGER     NOT NULL DEFAULT 0,
    error        TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ
);
