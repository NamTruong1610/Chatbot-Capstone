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
run_id, config_id, config_hash, git_sha, timestamp,
domain_id, case_id, question_type, access_level, role,
question, expected_answer, generated_answer,
should_abstain, did_abstain, abstention_correct,
n_sources, generation_latency_ms,
faithfulness, answer_relevancy, context_precision   # RAGAS, null if disabled
```

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

`grounded: false` means retrieval returned nothing and the abstention phrase was
returned without an LLM call (FR-GEN-06).

### `POST /api/crawl/site`

```json
// request
{"domain_id": "domain-a", "root_url": "https://…", "config_id": "C0-baseline"}

// response
{
  "domain_id": "domain-a",
  "document_id": "site:https://…",
  "manifest_path": "data/corpora/domain-a/crawl_20260801T0912.json",
  "pages_crawled": 37,
  "workflows_found": 6,
  "chunks_stored": 1284,
  "chunks_by_type": {"prose": 1180, "table": 62, "qa": 36, "workflow": 6},
  "index_fingerprint": {"chunking_hash": "…", "embedding_model": "…"}
}
```

Requires `X-API-Key`.
