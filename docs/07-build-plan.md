# 07 — Build Plan

13 weeks, Mon 27 Jul – Fri 23 Oct 2026. Phases follow the proposal's Research Schedule.
Task IDs trace to `docs/02-requirements.md`.

**Status legend:** ☐ not started · ◐ in progress · ☑ done

---

## Critical path

```
Config system ──→ Ingestion ──→ Chunking ──→ Retrieval ──→ Harness ──→ Sweeps
                                                              ↑
Test sets ────────────────────────────────────────────────────┘
```

Two things gate everything and are the usual causes of a blown schedule:

1. **The config system (P0).** Every component takes a resolved config in its
   constructor. Build it first and build it properly. Retrofitting configurability into
   working code in week 7 is how projects lose two weeks.
2. **The golden test sets.** The proposal already names these as the primary risk. They
   are manual, they take longer than anyone estimates, and no experiment can run without
   them. Start in week 1, in parallel with code — do not wait for the pipeline.

---

## Phase 0 — Foundations (W1–W2 · 27 Jul – 9 Aug)

Runs alongside the proposal's "Setup and Data Collection".

| ID | Task | Reqs | Acceptance |
|---|---|---|---|
| P0-1 | ☐ Repo scaffold, `pyproject.toml`, `Makefile`, `.env.example`, CI | NFR-05/06 | `make lint` and `make test` pass on an empty test suite |
| P0-2 | ☐ Config schema — pydantic models per section | FR-CFG-03 | Invalid enum, missing key, out-of-range all raise at load |
| P0-3 | ☐ Config loader — `extends` resolution, deep merge, cycle detection | FR-CFG-02/08 | Two-level extends merges correctly; cycle raises |
| P0-4 | ☐ Config hashing | FR-CFG-04 | Key reordering does not change the hash |
| P0-5 | ☐ `show` / `diff` / `validate` CLI | FR-CFG-06/07 | `diff C0 C2` prints only `retrieval.mode` and `reranker_model` |
| P0-6 | ☐ Write `C0-baseline.yaml` | — | Validates; hash is stable |
| P0-7 | ☐ Store adapters: Qdrant, Redis, Postgres + payload indexes | FR-STORE-01→07 | `make services` up; collection auto-created; all four payload indexes confirmed in logs; a filtered query on an empty collection returns cleanly |
| P0-8 | ☐ Strategy registries and protocols | `docs/04` §3 | A dummy chunker registers and is selectable by config |

**Gate:** a config file selects a no-op strategy end to end. No pipeline logic yet.

---

## Phase 1 — Ingestion (W2–W4 · 3 Aug – 23 Aug)

| ID | Task | Reqs | Acceptance |
|---|---|---|---|
| P1-1 | ☐ Crawler protocol + static backend | FR-CRAWL-01/03 | Crawls a fixture site to depth 2 |
| P1-2 | ☐ Playwright backend | FR-CRAWL-02 | Captures JS-injected content the static backend misses |
| P1-3 | ☐ Safety layer: robots, rate limit, blocklist | FR-CRAWL-05/07/08 | Blocked controls logged with reason; disallowed path raises |
| P1-4 | ☐ Affordance extraction: forms, tables, controls, headings | FR-CRAWL-04 | Fixture with a 3-field form yields all fields with labels + required flags |
| P1-5 | ☐ Interaction probing + state restore | FR-CRAWL-06 | Accordion click captures revealed text; page restored after |
| P1-6 | ☐ Raw corpus persistence + manifest | FR-CRAWL-09/10 | JSON written before processing; manifest lists skips and blocks |
| P1-7 | ☐ Idempotent re-ingest | FR-CRAWL-12 | Crawling twice yields the same chunk count |
| P1-8 | ☐ Affordance digest | FR-WF-01 | Digest size flat across a 2KB and a 200KB page |
| P1-9 | ☐ Two-pass workflow extraction | FR-WF-02/03/06/07 | Multi-page booking flow merges into one workflow; malformed JSON discarded |
| P1-10 | ☐ Access level assignment + `access_rule` | FR-ACL-01/02 | `/admin/*` → private, rule recorded |

**Gate:** `make crawl` produces a persisted corpus, a manifest, and a workflow list for a
real site.

---

## Phase 2 — Chunking and indexing (W4–W5 · 17 Aug – 30 Aug)

| ID | Task | Reqs | Acceptance |
|---|---|---|---|
| P2-1 | ☐ `fixed` chunker (Appendix A replication) | FR-CHUNK-01 | 3-line chunks; reproduces the Appendix A table split |
| P2-2 | ☐ `recursive` chunker | FR-CHUNK-01 | Respects size and overlap |
| P2-3 | ☐ `typed` chunker — workflow atomic, table header-repeat, qa paired, prose in headings | FR-CHUNK-02 | Table chunk carries headers; **the Appendix A table query now hits** |
| P2-4 | ☐ Heading breadcrumb, toggleable | FR-CHUNK-03 | Off/on changes chunk text only |
| P2-5 | ☐ Chunk metadata + validation | FR-CHUNK-05 | Missing `access_level` raises |
| P2-6 | ☐ Embedding + upsert, configurable model | FR-RET-10 | Dimension mismatch refuses to query |
| P2-7 | ☐ Index fingerprint written and verified | `docs/04` §5 | Evaluating a `typed` config against a `fixed` index refuses to run |
| P2-8 | ☐ Determinism test | FR-CHUNK-06 | Same page + config → byte-identical chunks |

**Gate:** three chunking strategies selectable by config, each producing a fingerprinted
index.

---

## Phase 3 — Retrieval and generation (W5–W6 · 24 Aug – 6 Sep)

| ID | Task | Reqs | Acceptance |
|---|---|---|---|
| P3-1 | ☐ Dense retriever | FR-RET-01 | Returns ranked chunks with full telemetry |
| P3-2 | ☐ BM25 sparse arm, per-domain cache + invalidation | FR-RET-02/09 | Cache rebuilds after ingest |
| P3-3 | ☐ RRF and weighted fusion | FR-RET-04 | RRF matches hand-computed ranks on a fixture |
| P3-4 | ☐ Cross-encoder reranker, lazy-loaded | FR-RET-03/06 | Not loaded under `dense` |
| P3-5 | ☐ Access strategies: prefilter, postfilter, none | FR-ACL-03/04/05 | `none` selectable only from the harness |
| P3-6 | ☐ Retrieval telemetry: per-arm ranks, latency | FR-RET-07/08 | Latency recorded per query |
| P3-7 | ☐ Prompt variants from `prompts/` | FR-GEN-03 | `strict_grounded` and `permissive` both load |
| P3-8 | ☐ Generation service: numbered context, citations, abstention | FR-GEN-04/05/06 | Empty retrieval returns abstention without an LLM call |
| P3-9 | ☐ Chat API + session/summary wiring | FR-API-01/03 | Contract matches `docs/05` §6 |

**Gate:** all three RQ1 retrieval modes answer a real question under both roles.

---

## Phase 4 — Harness (W6–W7 · 31 Aug – 13 Sep)

Proposal weeks 6–9 are "Experimentation and Development". The harness must land at the
*start* of that window, not the end.

| ID | Task | Reqs | Acceptance |
|---|---|---|---|
| P4-1 | ☐ Test set loader + validation | FR-EVAL-01 | Malformed row fails with line number |
| P4-2 | ☐ `metrics.py` — pure functions | FR-EVAL-04 | Unit-tested against hand-computed examples |
| P4-3 | ☐ Abstention routing and scoring | FR-EVAL-05 | Out-of-scope rows get null, not zero |
| P4-4 | ☐ Leakage counting | FR-EVAL-06/ACL-08 | Raw count reported per config × role |
| P4-5 | ☐ Single-config runner + `run.json` | FR-EVAL-02/07 | Every row carries config hash and git SHA |
| P4-6 | ☐ Sweep runner from `configs/sweeps/*.yaml` | FR-EVAL-03 | `make sweep RQ=1` runs C0, C1, C2 |
| P4-7 | ☐ Fingerprint guard | FR-EVAL-11 | Mismatched index refuses, names the config to re-ingest |
| P4-8 | ☐ Paired comparison: deltas, Wilcoxon, effect size | FR-EVAL-09 | Matches scipy on a fixture |
| P4-9 | ☐ Grouped summaries with n, SD, CI | FR-EVAL-08 | RQ1/RQ2/RQ4 tables emit |
| P4-10 | ☐ Reproducibility CI check | NFR-03 | Same config twice → identical metrics |

**Gate:** `make sweep RQ=1` produces the RQ1 comparison table end to end.

---

## Phase 5 — Configurations and experiments (W7–W9 · 7 Sep – 27 Sep)

| ID | Task | Reqs | Acceptance |
|---|---|---|---|
| P5-1 | ☐ Author `C1`–`C14` | `docs/03` §3 | Each `diff` against C0 shows exactly one manipulation |
| P5-2 | ☐ Ingest both domains under every chunking arm | — | See compute budget below |
| P5-3 | ☐ Run RQ1 sweep, both domains | RQ1 | Tables + paired comparisons |
| P5-4 | ☐ Run chunking sweep, both domains | Appendix A | `C0` vs `C5` effect size computed |
| P5-5 | ☐ Run RQ2 sweep under both roles | RQ2 | Leakage counts; `C12` ceiling established |
| P5-6 | ☐ Run supervisor ablations `C9`, `C10` | Supervisor | Workflow extraction's contribution isolated |
| P5-7 | ☐ QLoRA training script + run | RQ3 | Adapter trains within VRAM budget; cost recorded |
| P5-8 | ☐ Run RQ3 comparison | RQ3 | Includes `C14` prompt control |
| P5-9 | ☐ RAGAS integration, judge model pinned | FR-EVAL-10 | Judge version in `run.json` |
| P5-10 | ☐ RQ4 cross-domain grouping + rank correlation | RQ4 | Configuration orderings compared across domains |

**Gate:** every RQ has numbers.

---

## Phase 6 — Frontend and integration (W8–W9 · parallel, low priority)

| ID | Task | Reqs | Acceptance |
|---|---|---|---|
| P6-1 | ☐ Embeddable widget, style-isolated | FR-UI-01 | Renders correctly on two unrelated host pages |
| P6-2 | ☐ Source display | FR-UI-02 | Links open the cited page |
| P6-3 | ☐ Accessibility floor | FR-UI-03 | Keyboard nav, reduced motion, mobile width |
| P6-4 | ☐ Integration guide | Brief §4 | A third party could follow it unaided |

**Cut this first if the schedule slips.** The brief asks for a frontend, but no research
question depends on it. A thesis with no widget and complete RQ1–RQ4 results passes; the
reverse does not.

---

## Phase 7 — Analysis and writing (W10–W13 · 28 Sep – 23 Oct)

Per the proposal. W10–W12 analysis, comparison tables, charts, evaluation/discussion/
conclusion chapters. W13 final edit and submission.

**Freeze the code at end of W9.** Any change after that either invalidates results or
costs re-runs you do not have time for. Tag the commit and cite the tag in the thesis.

---

## Compute budget — the thing most likely to blow up

Chunking and embedding arms each require a **separate ingest per domain**
(`docs/04` §5). Retrieval and generation arms reuse an index.

| Arm | Ingests needed |
|---|---|
| `C0` typed | 2 (one per domain) |
| `C5` fixed, `C6` recursive, `C7` table-split, `C8` no-breadcrumb | 8 |
| `C9` no-workflows, `C10` no-interaction | 4 (different crawl or extraction) |
| Embedding variants, if run | 2 per model |
| `C1`–`C4`, `C11`–`C14` | 0 — reuse `C0` index |

**14+ full ingests.** Each is a crawl (minutes, network-bound, rate-limited) plus
embedding (minutes). Two implications:

- **Cache crawls.** Re-chunking must run from the persisted corpus JSON, never a fresh
  crawl. If chunking arms trigger re-crawls, this phase does not fit in the schedule.
- **Budget a full day in W7** for ingest runs alone, and script it as one command.

---

## Risks

| Risk | Trigger | Response |
|---|---|---|
| Test sets slip | Not complete by end W3 | Cut to 30 pairs/domain; use AI-synthesised pairs with manual validation, flag proportion (`docs/06` §9) |
| Interactive crawling breaks on real sites | Repeated failures in W3 | Fall back to `interaction_probing: false`; `C10` becomes the headline rather than an ablation |
| Playwright unusable on the dev machine | W2 | Static backend; **record it** (FR-CRAWL-03) and narrow the workflow claims |
| QLoRA exceeds VRAM | W8 | Smaller base model, or report RQ3 as a null with the resource constraint as the finding |
| Chunking arms do not fit the schedule | W8 | Run `C0` vs `C5` only. That single comparison is the Appendix A question and is worth more than `C6`–`C8` combined |
| Scope creep into production concerns | Any time | `docs/01` §7 is the scope boundary. Re-read it |

---

## Weekly rhythm

Yining gives feedback by message rather than structured meetings, so make async updates
easy to act on. Each Friday, post:

1. Requirement IDs completed
2. Any numbers produced, with the config id that produced them
3. Decisions needed — pull from `docs/08-open-decisions.md`

Keep `docs/08` current. An open decision that sits unanswered for two weeks becomes a
schedule risk, and the ones in there now block Phase 1.
