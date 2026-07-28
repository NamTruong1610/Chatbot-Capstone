# 02 — Requirements

Every requirement has an ID and a trace. Reference the ID in commit messages.

Priority: **M** must have (thesis fails without it) · **S** should have · **C** could have.

---

## FR-CFG — Configuration system

*The deliverable. Build this first; everything else plugs into it.*

| ID | Requirement | Pri | Trace |
|---|---|---|---|
| FR-CFG-01 | Configurations are declarative YAML files in `configs/`, one per named configuration. | M | All RQs |
| FR-CFG-02 | A config may `extends:` another; the child's values override the parent's by deep merge. Exactly one root config (`C0-baseline`) has `extends: null`. | M | All RQs |
| FR-CFG-03 | Configs are validated against a typed schema on load. Unknown keys, missing required keys, and out-of-range values raise at load time, not at use time. | M | Rule 2 |
| FR-CFG-04 | Every config resolves to a deterministic `config_hash` (stable hash of the fully-merged dict). Reordering keys must not change the hash. | M | Reproducibility |
| FR-CFG-05 | The resolved config is injected into every component. No component reads a global or an env var for a pipeline parameter. | M | Rule 1 |
| FR-CFG-06 | `python -m chatbot.config show <config_id>` prints the fully resolved config and its hash. | S | Debugging |
| FR-CFG-07 | `python -m chatbot.config diff <a> <b>` prints only the differing keys — the experimental manipulation, made explicit. | S | Write-up |
| FR-CFG-08 | Loading a config whose `extends` chain contains a cycle raises. | S | Robustness |

## FR-STORE — Vector store

*Qdrant with cosine distance. Decided in `docs/08` OD-1; not an experimental variable.*

| ID | Requirement | Pri | Trace |
|---|---|---|---|
| FR-STORE-01 | The vector store is accessed through one adapter module. No other module imports the Qdrant client directly. | M | `docs/04` §6 |
| FR-STORE-02 | The collection is created on startup if absent, with the dimensions implied by `embedding.model` and `store.distance`. | M | Setup |
| FR-STORE-03 | Payload indexes are created on `domain_id`, `access_level`, `document_id`, `chunk_type` at startup. Their absence must not be silent — log the creation or the confirmation that they exist. | M | FR-RET-08, RQ2 |
| FR-STORE-04 | Filtered search passes `domain_id` and permitted `access_level` values as a server-side payload filter on the same call as the vector query. Filtering after the fact is `postfilter` (FR-ACL-04) and must not be used to implement `prefilter`. | M | RQ2 |
| FR-STORE-05 | A stored vector's dimension count is validated against `embedding.dimensions` at upsert. A mismatch raises rather than writing. | M | FR-RET-10 |
| FR-STORE-06 | `embedding.normalize: false` combined with `store.distance: cosine` raises at config load unless an explicit acknowledgement flag is set. The L2/cosine equivalence relied on elsewhere assumes normalised vectors. | S | Correctness |
| FR-STORE-07 | Upserts are batched. A crawl producing several thousand chunks must not issue one request per chunk, nor one request for all of them. | S | Reliability |

## FR-CRAWL — Autonomous site ingestion

| ID | Requirement | Pri | Trace |
|---|---|---|---|
| FR-CRAWL-01 | Given a root URL, crawl same-origin pages breadth-first to `ingestion.max_depth`, capped at `ingestion.max_pages`. | M | Supervisor |
| FR-CRAWL-02 | Render JavaScript (headless browser) so SPA and dynamically-injected content is captured. | M | Supervisor |
| FR-CRAWL-03 | Degrade to a static HTML fetch if the browser backend is unavailable, and **record which backend was used in the crawl manifest**. Results from different backends are not comparable. | M | Reproducibility |
| FR-CRAWL-04 | Per page, extract: cleaned main text, heading hierarchy, forms (fields, labels, types, required flags, submit label, action), tables (caption, headers, rows), links, and interactive controls. | M | Supervisor |
| FR-CRAWL-05 | **Never activate a control that could submit, purchase, delete, authenticate, or log out.** Blocklist is configurable and defaults to a conservative pattern set. Log every control skipped and why. | M | Ethics |
| FR-CRAWL-06 | When `ingestion.interaction_probing` is on, click permitted controls, capture the resulting page-text delta as that control's revealed content, and restore prior state. | M | Supervisor |
| FR-CRAWL-07 | Honour `robots.txt`; refuse to crawl a disallowed path and raise a clear error. | M | Ethics |
| FR-CRAWL-08 | Rate-limit to `ingestion.request_delay_seconds` between requests; send an identifying User-Agent. | M | Ethics |
| FR-CRAWL-09 | Persist raw crawl output to `data/corpora/<domain_id>/crawl_<timestamp>.json` **before** any processing. The corpus must survive the site changing mid-project. | M | Risk register |
| FR-CRAWL-10 | Emit a crawl manifest: root URL, timestamp, backend used, pages fetched, pages skipped with reasons, controls probed, controls blocked, wall time. | M | Reproducibility |
| FR-CRAWL-11 | A dry-run mode reports what would be extracted without writing to the vector store. | S | Dev loop |
| FR-CRAWL-12 | Re-ingestion is idempotent: crawling the same site twice into the same `domain_id` must not duplicate chunks. | M | Correctness |

## FR-WF — Workflow extraction

| ID | Requirement | Pri | Trace |
|---|---|---|---|
| FR-WF-01 | Compress each page to a bounded **affordance digest** before any LLM call. Digest size must not scale with page length. | M | Supervisor (token limit) |
| FR-WF-02 | Pass 1: derive candidate workflows from a single page's digest. | M | Supervisor |
| FR-WF-03 | Pass 2: consolidate candidates across pages into merged workflows using the link graph. A workflow may span pages. | M | Supervisor |
| FR-WF-04 | A workflow has: name, trigger, ordered steps, preconditions, outcome, source URLs, access level, confidence. | M | — |
| FR-WF-05 | Confidence is keyed to evidence quality: form-driven > click-driven > prose-inferred. Record which. | S | Analysis |
| FR-WF-06 | Discard workflows with fewer than two steps. A page describing a service is not a workflow. | M | Hallucination |
| FR-WF-07 | Malformed LLM output is discarded with a warning, never partially parsed into a workflow. | M | Hallucination |
| FR-WF-08 | `ingestion.workflow_extraction` can be disabled, yielding a prose-only knowledge base. **This is an experimental arm** — see `docs/03` §C4. | M | Supervisor ablation |
| FR-WF-09 | Extraction runs at `temperature: 0.0`. | M | Determinism |

## FR-CHUNK — Chunking

| ID | Requirement | Pri | Trace |
|---|---|---|---|
| FR-CHUNK-01 | Support at least three selectable strategies: `fixed` (naive fixed-size **character** windows of `chunking.size`, hard-cut with no boundary respect — the naive RAG baseline / Appendix A condition; **not** line-based, see OD-13), `recursive` (character splitter honouring `size`/`overlap` and backing off to separators so it does not cut mid-unit), `typed` (rule per content type). `fixed` and `recursive` differ precisely in boundary respect. | M | Appendix A |
| FR-CHUNK-02 | `typed` strategy rules: `workflow` never split · `table` split by row group with header and caption repeated on every chunk · `qa` question and answer together · `prose` recursive split within heading boundaries. | M | Appendix A |
| FR-CHUNK-03 | Under `typed`, each prose chunk is prefixed with its heading breadcrumb. Toggleable via `chunking.heading_breadcrumb`. | S | Retrieval quality |
| FR-CHUNK-04 | `chunking.size` and `chunking.overlap` are configurable and apply to strategies that use them. | M | RQ1 |
| FR-CHUNK-05 | Every chunk carries the metadata in `docs/05-data-contracts.md` §1. Missing required metadata raises at ingest. | M | RQ2 |
| FR-CHUNK-06 | Chunking is pure and testable: given the same page object and config, output is byte-identical. No network, no LLM. | M | Determinism |

## FR-RET — Retrieval

| ID | Requirement | Pri | Trace |
|---|---|---|---|
| FR-RET-01 | `retrieval.mode: dense` — vector similarity only. The RQ1 baseline. | M | RQ1 |
| FR-RET-02 | `retrieval.mode: hybrid` — dense + BM25, results fused. | M | RQ1 |
| FR-RET-03 | `retrieval.mode: hybrid_rerank` — hybrid, then cross-encoder reranks fused candidates. | M | RQ1 |
| FR-RET-04 | `retrieval.fusion` selects `rrf` or `weighted`. RRF is default; rationale in `docs/03` §4.2. | S | RQ1 |
| FR-RET-05 | `retrieval.top_k` and `retrieval.candidate_k` configurable; `candidate_k >= top_k` enforced at config load. | M | RQ1 |
| FR-RET-06 | `retrieval.reranker_model` configurable; loaded lazily so `dense` and `hybrid` runs do not pay for it. | S | Resource limits |
| FR-RET-07 | Every retrieved chunk returns: id, text, full metadata, fused score, rank in each arm that found it, rerank score if applicable. | M | Analysis |
| FR-RET-08 | Retrieval reports wall-clock latency per query. Latency is a first-class SME result, not a footnote. | M | RQ1, contribution |
| FR-RET-09 | The sparse index is per-`domain_id`, cached, and invalidated on any write to that domain. | M | Correctness |
| FR-RET-10 | `embedding.model` is configurable. Changing it requires re-indexing; the system must detect a dimension mismatch and refuse to query rather than return garbage (FR-STORE-05). | M | RQ4 |

## FR-ACL — Access control

| ID | Requirement | Pri | Trace |
|---|---|---|---|
| FR-ACL-01 | Every chunk carries `access_level ∈ {public, private}`, assigned at ingest. | M | RQ2 |
| FR-ACL-02 | Assignment sources, in precedence order: explicit per-document override → URL pattern rules from config → default `public`. Record which rule fired. | M | RQ2 |
| FR-ACL-03 | `access_control.strategy: prefilter` — filter by permitted levels **before** scoring, on both retrieval arms. Dense arm: server-side payload filter (FR-STORE-04). Sparse arm: mask disallowed documents before ranking, so the top-*n* is the top-*n* of what the role may see. | M | RQ2 |
| FR-ACL-04 | `access_control.strategy: postfilter` — retrieve unfiltered, then drop impermissible chunks. Present as an experimental arm for comparison against ARBITER-style approaches (Lorenzo et al., 2025). | M | RQ2 |
| FR-ACL-05 | `access_control.strategy: none` — no filtering. Control condition establishing the leakage ceiling. **Must be impossible to select outside the evaluation harness.** | M | RQ2, safety |
| FR-ACL-06 | Role→levels mapping is config-driven, not hardcoded. Default: `customer → {public}`, `admin → {public, private}`. | M | RQ2 |
| FR-ACL-07 | A redundant post-retrieval assertion runs under `prefilter` and logs an error if it ever drops a chunk. In a correct run it never fires. | S | Defence in depth |
| FR-ACL-08 | Leakage is counted and reported per run as a **raw count**, never only as a rate. | M | RQ2 |

## FR-GEN — Generation

| ID | Requirement | Pri | Trace |
|---|---|---|---|
| FR-GEN-01 | `generation.model` and `generation.base_url` configurable, so a fine-tuned model substitutes without code changes. | M | RQ3 |
| FR-GEN-02 | `generation.adapter` optionally names a QLoRA adapter to load. | M | RQ3 |
| FR-GEN-03 | `generation.prompt_variant` selects a named prompt template from `prompts/`. At minimum `strict_grounded` and `permissive` (a control that does not instruct abstention). | M | RQ1/RQ3 |
| FR-GEN-04 | Under `strict_grounded`, the model must abstain with an exact configured phrase when context is insufficient. | M | Hallucination |
| FR-GEN-05 | Retrieved chunks are numbered in the prompt and the model cites markers. Responses return a source list with URLs. | S | Trust, RQ1 |
| FR-GEN-06 | If retrieval returns nothing, return the abstention phrase without calling the LLM. | M | Cost, correctness |
| FR-GEN-07 | Conversation history passed to the model is bounded by `generation.history_turns`. | S | Context limits |
| FR-GEN-08 | `generation.temperature` defaults to 0.0 for evaluation. Non-zero requires an explicit flag and is recorded in results. | M | Determinism |

## FR-EVAL — Evaluation harness

| ID | Requirement | Pri | Trace |
|---|---|---|---|
| FR-EVAL-01 | Load golden test sets in the schema at `docs/05-data-contracts.md` §2. Malformed rows fail loudly with line numbers. | M | All RQs |
| FR-EVAL-02 | Run one named configuration across one or more domains, emitting per-question rows. | M | All RQs |
| FR-EVAL-03 | Run a **sweep**: a named list of configurations, sequentially, into one results directory. | M | All RQs |
| FR-EVAL-04 | Compute retrieval metrics per `docs/06-evaluation-protocol.md`: precision@k, recall@k, MRR, hit rate. | M | RQ1, RQ4 |
| FR-EVAL-05 | Score questions the system *should* fail (out-of-scope; private-asked-as-customer) on **abstention correctness**, not retrieval accuracy. | M | RQ2 |
| FR-EVAL-06 | Report leakage count per configuration and role. | M | RQ2 |
| FR-EVAL-07 | Every results row carries `config_id`, `config_hash`, `domain_id`, `role`, `question_type`, timestamp, git SHA. | M | Reproducibility |
| FR-EVAL-08 | Emit grouped summaries: by mode (RQ1), by role × access level (RQ2), by domain × question type (RQ4). | M | Write-up |
| FR-EVAL-09 | Support **paired comparison** between two configurations on the same questions, reporting per-question deltas and a paired significance test. | M | `docs/01` §6 |
| FR-EVAL-10 | Integrate RAGAS for faithfulness, answer relevancy, context precision. Toggleable — it costs an LLM call per question. | S | RQ1, RQ3 |
| FR-EVAL-11 | Refuse to run if the corpus was ingested under a different `chunking`/`embedding` config than the one being evaluated. Comparing a `typed` index with a `fixed` config is a silent, catastrophic error. | M | Correctness |
| FR-EVAL-12 | Results are append-only. Re-running the same config writes a new timestamped directory. | S | Audit trail |

## FR-API / FR-UI — Serving layer

| ID | Requirement | Pri | Trace |
|---|---|---|---|
| FR-API-01 | `POST /api/chat/message` accepts message, `domain_id`, `user_id`, `session_id`, `role`; returns reply, sources, grounded flag, retrieval telemetry. | M | Brief |
| FR-API-02 | Ingestion and crawl endpoints require an API key; chat does not. | M | Brief |
| FR-API-03 | Session history in Redis with TTL; summarised to Postgres on session end. | S | Existing design |
| FR-API-04 | The active configuration is reported by the health endpoint. | S | Ops |
| FR-UI-01 | A single-script-tag embeddable widget, style-isolated from the host page. | M | Brief |
| FR-UI-02 | The widget displays source links returned by the API. | S | Trust |
| FR-UI-03 | Keyboard accessible, respects reduced motion, works at mobile widths. | S | Quality floor |

---

## NFR — Non-functional

| ID | Requirement | Pri |
|---|---|---|
| NFR-01 | Runs end-to-end on one machine with ≤16GB VRAM. | M |
| NFR-02 | A full evaluation run over one domain (≈50 questions, one config) completes in under 30 minutes. | S |
| NFR-03 | Identical config + identical corpus ⇒ identical metrics on re-run. | M |
| NFR-04 | Unit tests run with no network and no running services. | M |
| NFR-05 | Type hints on all public functions; `make lint` clean. | S |
| NFR-06 | No secrets in the repo. `.env` gitignored, `.env.example` committed. | M |
| NFR-07 | Raw corpora committed or archived so results are reproducible after the source sites change. | M |
