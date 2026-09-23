-- Conversation persistence schema (Phase 8, FR-API-01/03; OD-16).
--
-- Two tables. A conversation is scoped by (domain_id, role) fixed at creation; its messages are
-- an ordered log. This is the LIVE store — FR-API-03's Redis hot-path and summary-on-end are
-- deferred (OD-16), so history is read straight from here. Idempotent (IF NOT EXISTS) so the app
-- can run it at startup, the same way the Qdrant collection auto-creates.

CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY,
    domain_id       TEXT        NOT NULL,
    -- role is pinned here and checked on every append: a conversation cannot change role
    -- mid-stream, so a customer can never replay a staff conversation's history (RQ2 isolation
    -- extended into the conversation layer — fail closed).
    role            TEXT        NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS messages (
    id              BIGSERIAL   PRIMARY KEY,
    conversation_id TEXT        NOT NULL REFERENCES conversations (conversation_id),
    -- 0-based position within the conversation; strict order for reconstructing exchanges.
    turn_index      INTEGER     NOT NULL,
    sender          TEXT        NOT NULL CHECK (sender IN ('user', 'assistant')),
    content         TEXT        NOT NULL,
    -- Provenance for assistant turns (null on user turns):
    grounded        BOOLEAN,
    sources         JSONB       NOT NULL DEFAULT '[]'::jsonb,
    -- The standalone query the follow-up was condensed to before retrieval (FR-GEN-08) — kept so
    -- a bad multi-turn retrieval can be traced back to its rewrite (decision 7).
    search_query    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (conversation_id, turn_index)
);

-- History is always read by conversation, newest turns last; index the access path.
CREATE INDEX IF NOT EXISTS messages_conversation_turn_idx
    ON messages (conversation_id, turn_index);
