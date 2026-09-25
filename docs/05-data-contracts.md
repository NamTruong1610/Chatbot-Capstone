# 05 — Data Contracts

Changing anything in this document invalidates already-collected results. If a contract
must change, say so explicitly in the commit and flag which results need re-running.

---

## 1. Chunk payload

Every chunk stored in the vector database carries this payload. Required fields missing
at ingest → raise (FR-CHUNK-05).

```python
{
  # ── identity ──────────────────────────────────────────
  "chunk_id":        str,    # required, unique
  "domain_id":       str,    # required — tenant partition
  "document_id":     str,    # required — "site:<root_url>" or upload uuid
  "chunk_index":     int,    # required — position within document

  # ── content ───────────────────────────────────────────
  "text":            str,    # required — the embedded text
  "chunk_type":      str,    # required — workflow | table | qa | prose

  # ── access control (RQ2) ──────────────────────────────
  "access_level":    str,    # required — public | private
  "access_rule":     str,    # required — which rule assigned it:
                             #   "explicit" | "url_pattern:<pattern>" | "default"

  # ── provenance ────────────────────────────────────────
  "source_url":      str,    # "" for uploads
  "page_title":      str,
  "heading_path":    str,    # breadcrumb, e.g. "Enrolment > Subject withdrawal"
  "filename":        str,    # uploads only

  # ── type-specific ─────────────────────────────────────
  "workflow_name":   str,    # workflow only
  "step_count":      int,    # workflow only
  "confidence":      float,  # workflow only — evidence quality
  "all_source_urls": list,   # workflow only — may span pages
  "table_index":     int,    # table only
  "row_range":       [int, int],   # table only
  "question":        str,    # qa only
  "revealed_by":     str,    # prose revealed by clicking a control

  # ── audit ─────────────────────────────────────────────
  "ingest_source":   str,    # crawl | upload
  "config_id":       str,    # required — which config built this chunk
  "chunking_hash":   str,    # required — see docs/04 §5
  "index_key":       str,    # required — chunking+embedding fingerprint (docs/04 §5); the
                             #   discriminator that partitions the shared collection so a
                             #   dense run over one config never scores another's vectors
  "ingested_at":     str,    # ISO 8601 UTC
}
```

**Indexed fields.** `domain_id`, `access_level`, `document_id`, `chunk_type` **and
`index_key`** each require a Qdrant payload index (`PayloadSchemaType.KEYWORD`), created at
startup (FR-STORE-03). Without them every filtered query scans the collection, and since
`latency_ms` is a reported RQ1 result, an unindexed run measures the missing index rather
than the retrieval architecture. `index_key` is indexed because every query filters on it
(it selects the config's own index within the shared collection).

---

## 2. Golden test set

`data/testsets/<domain_id>.csv`. UTF-8, header row required, RFC 4180 quoting.

```csv
question,answer,source_page,question_type,access_level,answer_terms,notes
"When does enrolment open for undergraduate Engineering students?","Thursday 27 November 2025",page_1.txt,factual_lookup,public,enrolment;27 November 2025,
"What steps do I take to enrol in a Summer subject from another faculty?","Check self-enrol eligibility, then submit an eRequest",page_5.txt;page_2.txt,multi_chunk,public,,"spans two pages; open-ended -> answer-span null"
"What is the GPA requirement for Summer session?",N/A,,out_of_scope,public,,"not in corpus"
"Which students have sanctions preventing enrolment?","Restricted to administrative staff",N/A,factual_lookup,private,,
```

| Column | Required | Values |
|---|---|---|
| `question` | yes | Non-empty. The query issued verbatim. |
| `answer` | yes | Expected answer, or `N/A` for out-of-scope/private. |
| `source_page` | conditional | Page identifier(s), `;`-separated. **Empty for `out_of_scope`.** Required otherwise. |
| `question_type` | yes | `factual_lookup` · `reasoning` · `multi_chunk` · `out_of_scope` |
| `access_level` | yes | `public` · `private` |
| `answer_terms` | no | The answer's *usable unit* for answer-span (§06 §1.1): `;`-separated components, each `|`-separated alternatives. Empty ⇒ answer-span null for the case. Authored blind to the configs. |
| `notes` | no | Free text for the researcher. Never parsed. |

### Validation rules (FR-EVAL-01)

Fail loudly with the line number if:

- `question_type == out_of_scope` **and** `source_page` is non-empty
- `question_type != out_of_scope` **and** `source_page` is empty
- `question_type == multi_chunk` **and** `source_page` names fewer than two pages
- Any `question_type` or `access_level` outside the enum
- Duplicate `question` within a file

### Composition targets

Per domain, 30–50 pairs. Aim for roughly:

| Type | Share | Why |
|---|---|---|
| `factual_lookup` | ~40% | The bulk of real SME queries |
| `reasoning` | ~20% | Where reranking should show its value |
| `multi_chunk` | ~20% | Where chunking strategy shows its value — do not under-sample |
| `out_of_scope` | ~20% | The only way to measure abstention; RAG's residual hallucination lives here |

At least 20% of pairs should be `access_level: private`, or RQ2 has almost no signal.

**`source_page` identifiers must be stable across chunking configs.** Use the page URL
or the crawl-assigned page id — never a chunk id, because chunk ids change whenever
chunking changes, and chunking is an experimental arm (`docs/03` §3).

---

## 3. Access level semantics

| Level | Meaning |
|---|---|
| `public` | Any visitor may see it. Content reachable without authentication. |
| `private` | Staff/admin only. Content behind a login, or on an admin/staff path. |

Assignment precedence (FR-ACL-02), highest first:

1. **Explicit** — per-document override supplied at ingest
2. **URL pattern** — `access_control.private_url_patterns` matched against the source URL
3. **Default** — `access_control.default_level`, normally `public`

The rule that fired is recorded in `access_rule`. This matters: if RQ2 shows leakage
under `prefilter`, the cause is almost certainly mislabelling at ingest rather than a
retrieval bug, and `access_rule` is how you find out which rule was wrong.

Role mapping is additive and config-driven:

```yaml
role_map:
  customer: [public]
  admin:    [public, private]
```

**Fail closed.** An unrecognised role resolves to the empty set and returns nothing. It
never falls back to `customer`.

---

## 4. Crawl manifest

`data/corpora/<domain_id>/crawl_<timestamp>.json`, written before any processing.

```json
{
  "domain_id": "domain-a",
  "root_url": "https://example.com.au",
  "started_at": "2026-08-01T09:12:03Z",
  "finished_at": "2026-08-01T09:31:44Z",
  "backend": "playwright",
  "config_id": "C0-baseline",
  "max_pages": 40,
  "max_depth": 3,
  "pages_fetched": 37,
  "pages_skipped": [
    {"url": "…", "reason": "robots_disallow"},
    {"url": "…", "reason": "non_html"}
  ],
  "controls_probed": 84,
  "controls_blocked": [
    {"url": "…", "label": "Confirm booking", "reason": "destructive_pattern"}
  ],
  "pages": [ /* CrawledPage objects */ ]
}
```

`controls_blocked` is not debug output — it is the ethics audit trail. It evidences that
the crawler never activated a transactional control on a live commercial site. Keep it.

**Per-document access override (FR-ACL-02 tier 1).** A page object may carry an explicit
`"access_level": "public" | "private"`. It is the highest-precedence label rule — it beats the
URL-pattern and default rules at ingest (`ingestion/access.py`). This is how **uploaded** private
content (e.g. staff docs that are not URL-addressable) is marked private: put those pages in a
separate JSON and ingest them alongside the public corpus with `ingest --private-corpus <file>`
(one partition rebuild — a second `ingest` would wipe the public partition). Absent the field, the
URL-pattern/default rules apply as before.

---

## 5. Results schemas

### 5.1 Per-question retrieval rows

`results/<timestamp>-<config_id>/retrieval.csv`

```
run_id, config_id, config_hash, git_sha, timestamp,
domain_id, case_id, question_type, access_level, role,
scored_as,                      # retrieval | abstention
chunks_returned, chunk_types,   # JSON list
precision_at_k, recall_at_k, mrr, hit_rate,
answer_hit_at_k, answer_precision_at_k,   # answer-span (docs/06 §1.1); null if no unit
leaked_chunks, latency_ms,
retrieved_sources               # JSON list, ordered
```

`precision_at_k` … `hit_rate` are **null** when `scored_as == "abstention"`. Null is not
zero — see `docs/06` §3. `answer_hit_at_k`/`answer_precision_at_k` are additionally null when
the case declares no `answer_terms` unit (docs/06 §1.1) — answer-span scores only cases with
an authored single-place answer.

### 5.2 Per-question generation rows

`results/<timestamp>-<config_id>/generation.csv`

```
config_id, config_hash, git_sha, timestamp,
domain_id, case_id, question_type, access_level, role,
question, expected_answer, generated_answer,
should_abstain, did_abstain, abstention_correct,
fact_contained,                                     # interim grounding proxy (below); null if unchecked
n_sources, generation_latency_ms,
faithfulness, answer_relevancy, context_precision   # RAGAS, null if disabled
```

`abstention_correct` is `should_abstain == did_abstain` (docs/06 §3). `fact_contained` is the
**interim grounding proxy** (OD-14): for an *answered* case with an authored `answer_terms`
unit, whether the generated answer contains that unit (`metrics.is_answer_relevant` — the same
ruler as retrieval answer-span). It is **null** when the case abstained or has no unit. It checks
fact **containment, not answer quality**; it stands in for the RAGAS columns until those land.
(`run_id` from earlier drafts is not emitted — run identity is the timestamped dir + `run.json`,
as with §5.1.)

### 5.3 Summaries

`rq1_retrieval.csv`, `rq2_access.csv`, `rq4_domains.csv` — grouped means with `n`,
standard deviation, and 95% CI per group. Point estimates alone are not reportable at
this sample size (`docs/01` §6).

### 5.4 Run metadata

`results/<timestamp>-<config_id>/run.json` — resolved config, config hash, git SHA,
index fingerprints for every domain touched, hardware summary, wall time, and the
library versions of embedding/rerank/LLM. Without this a result is not reproducible.

---

## 6. API contracts

### `POST /api/chat/message`

```json
// request
{
  "message": "How do I withdraw from a subject?",
  "domain_id": "domain-a",
  "user_id": "uuid",
  "session_id": "uuid",
  "role": "customer"
}

// response
{
  "reply": "…",
  "session_id": "uuid",
  "grounded": true,
  "sources": [{"marker": 1, "url": "https://…", "title": "Enrolment changes"}],
  "retrieval": {
    "config_id": "C2-hybrid-rerank",
    "mode": "hybrid_rerank",
    "role": "customer",
    "chunks_used": 5,
    "latency_ms": 412.7
  }
}
```

**Implemented subset (Phase 8).** The endpoint currently returns
`{answer, sources (URL strings), grounded, session_id?}` — the richer `reply`/`retrieval`
telemetry above is aspirational and not yet wired. `session_id` is **omitted** from the response
of a stateless request (no `session_id` in the body), so an existing single-shot caller receives
exactly `{answer, sources, grounded}` unchanged; it is echoed when the turn is part of a
conversation. `role` and `domain_id` remain optional; a `domain_id` that does not match the
server's configured domain is a 400.

**Session semantics (decision 5).** Omitting `session_id` → stateless single-shot (nothing
persisted). Providing one → the turn joins that conversation: history is loaded, the follow-up is
condensed (FR-GEN-09), and both messages are persisted. The client supplies the id (any fresh
string) on the first turn; the server creates the conversation on first sight. A `session_id`
reused under a different `role`/`domain_id` than it was created with is refused **403**
(fail-closed scope, RQ2 isolation in the conversation layer).

### `GET /api/chat/conversation/{session_id}`

Returns the stored message log for a conversation. No API key (chat is unauthenticated, FR-API-02).

```json
{
  "session_id": "uuid",
  "messages": [
    {"turn_index": 0, "sender": "user", "content": "Tell me about the Diploma of Business",
     "grounded": null, "sources": [], "search_query": null},
    {"turn_index": 1, "sender": "assistant", "content": "It is a 12-month course…",
     "grounded": true, "sources": ["https://…/courses"],
     "search_query": "Tell me about the Diploma of Business"}
  ]
}
```

---

## 7. Conversation store (Postgres)

The live store for multi-turn chat (Phase 8, OD-16). Two tables; DDL in
`db/conversation_schema.sql` (the single source of truth `ensure_schema()` runs at startup,
idempotent). The DSN is infrastructure, read from `CHATBOT_POSTGRES_DSN` — **not** a config
section, so it never enters `config_hash`. This store is **not** a results contract: it holds
serving state, and no research question reads it, so changing it does not invalidate any RQ result.

### 7.1 `conversations`

| Column | Type | Notes |
|---|---|---|
| `conversation_id` | `text` PK | Client-supplied on the first turn (the `session_id`). |
| `domain_id` | `text` | Fixed at creation. |
| `role` | `text` | Fixed at creation. A mismatched reuse fails closed (403). |
| `created_at` | `timestamptz` | Default `now()`. |
| `updated_at` | `timestamptz` | Touched on each append. |

### 7.2 `messages`

| Column | Type | Notes |
|---|---|---|
| `id` | `bigserial` PK | |
| `conversation_id` | `text` | FK → `conversations`. |
| `turn_index` | `int` | 0-based position; `UNIQUE(conversation_id, turn_index)`. |
| `sender` | `text` | `user` \| `assistant` (CHECK-constrained). |
| `content` | `text` | The message text. |
| `grounded` | `bool` | Assistant turns only; null on user turns. |
| `sources` | `jsonb` | List of source URLs; `[]` on user turns. |
| `search_query` | `text` | The standalone query the follow-up was condensed to (FR-GEN-09), for tracing a bad multi-turn retrieval back to its rewrite. Null on user turns / first turns without a rewrite. |
| `created_at` | `timestamptz` | Default `now()`. |

A conversation's history is reconstructed by pairing each `user` message with the `assistant`
reply that follows it, bounded to the last `generation.history_turns` completed exchanges. A
trailing user message with no reply yet contributes no exchange.

`grounded: false` means retrieval returned nothing and the abstention phrase was
returned without an LLM call (FR-GEN-06).

### `POST /api/crawl/site` — add a business (FR-API-05)

Crawls a URL, ingests it, and registers the domain. **Asynchronous:** the crawl runs as a
background task (it can take minutes), so the endpoint returns at once with the business in
`pending` state; poll `GET /api/crawl/site/{domain_id}` for progress. Requires `X-API-Key`
(FR-API-02); with no admin token configured it fails closed (503).

```json
// request  (bounds and corpus_path optional)
{
  "domain_id": "cutpro", "root_url": "https://…", "display_name": "CutPro",
  "max_pages": 12, "max_depth": 2,
  "corpus_path": null
}

// response (immediate) — a BusinessOut, status "pending"
{"domain_id": "cutpro", "display_name": "CutPro", "root_url": "https://…",
 "status": "pending", "chunk_count": 0, "error": null}
```

`corpus_path` is the **cached fallback**: set it to a previously-saved crawl JSON
(`data/corpora/<domain_id>/crawl_<ts>.json`, persisted on an earlier live crawl per FR-CRAWL-09)
to re-ingest without crawling — the demo's insurance against a slow or unreachable site. Bounds
(`max_pages`/`max_depth`) apply only to `ingestion`, so `index_key` and every RQ fingerprint are
unchanged. Robots and the control blocklist are honoured and not bypassable (FR-CRAWL-05/07).

### `GET /api/crawl/site/{domain_id}` — ingest status

Returns the `BusinessOut` for the domain (`pending` → `crawling` → `ready` | `failed`, with
`chunk_count` and `error`), or 404 if unknown. `failed` carries the reason; a failed add never
leaves a queryable-looking domain.

### `GET /api/domains` — the business registry

Read-only (no key — the future selector reads it). Lists every queryable business: those added
through the endpoint plus those ingested via the CLI (Wyatt, Austral), reconciled from the
fingerprint registry at startup.

```json
{"domains": [
  {"domain_id": "wyatt-edu", "display_name": "wyatt-edu", "root_url": "",
   "status": "ready", "chunk_count": 812, "error": null},
  {"domain_id": "cutpro", "display_name": "CutPro", "root_url": "https://…",
   "status": "ready", "chunk_count": 96, "error": null}
]}
```

A chat request (`POST /api/chat/message`) with a `domain_id` is served by that domain's pipeline,
built once and cached; a domain with no index returns **404** (not a crash).

The `businesses` table backing all three is in §8.

### `POST /api/ingest/private` — add private staff content (FR-API-06)

Ingests pasted text as `access_level=private` for a domain, **appended** to its existing index (no
crawl, no rebuild — public content is preserved). Synchronous. Requires `X-API-Key` (FR-API-02).

```json
// request
{"domain_id": "wyatt-edu", "title": "Escalation contacts", "text": "Escalate audits to Dana Fox…"}

// response
{"domain_id": "wyatt-edu", "title": "Escalation contacts", "chunks_added": 1, "access_level": "private"}
```

The text becomes a synthetic private page `internal://<domain_id>/<slug(title)>`, labelled private
via the tier-1 explicit override (docs/05 §1 `access_rule="explicit_override"`) — the same path the
file-based private corpus uses. A **customer** query never retrieves it; a **staff** query does
(prefilter + enforce, RQ2). An uningested domain returns **404**; no admin token → **503**.
Re-adding the same title+text is idempotent (deterministic chunk ids).

---

## 8. Business registry (Postgres)

One row per business/domain the app knows about (Phase 9, FR-API-05). DDL in
`db/business_schema.sql`, idempotent, run at startup on the same Postgres as the conversation
store. **Not a results contract** — it holds serving state, no research question reads it, so
changing it invalidates no RQ result. The `status` column doubles as the async ingest-job state,
so a long crawl's progress is durable and pollable without a separate jobs table.

### 8.1 `businesses`

| Column | Type | Notes |
|---|---|---|
| `domain_id` | `text` PK | The domain; endpoint-supplied or CLI-reconciled. |
| `display_name` | `text` | For the selector; defaults to `domain_id`. |
| `root_url` | `text` | The crawl root (empty for CLI-reconciled domains). |
| `status` | `text` | `pending` → `crawling` → `ready` \| `failed`. |
| `chunk_count` | `int` | Chunks ingested (0 until `ready`). |
| `error` | `text` | The failure reason on `failed`; null otherwise. |
| `created_at` | `timestamptz` | Default `now()`. |
| `updated_at` | `timestamptz` | Touched on each state change. |

CLI-ingested domains (Wyatt, Austral) have no row until reconciled: at startup every fingerprint
in `data/index/fingerprints.json` without a row is inserted as `ready` with its chunk count, so
`GET /api/domains` lists all businesses, not only endpoint-added ones. A domain the registry
already tracks (e.g. an in-flight add) is never overwritten by a stale fingerprint.
