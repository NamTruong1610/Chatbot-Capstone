# 03 — Configuration Matrix

**This document defines the deliverable.** Everything else in the repo exists to make
these configurations runnable and comparable.

---

## 1. Format

One YAML file per configuration in `configs/`. `C0-baseline.yaml` is the root; every
other config `extends` it and overrides only what it manipulates.

```yaml
id: C2-hybrid-rerank
extends: C0-baseline
description: >
  Adds cross-encoder reranking over the fused candidate set. RQ1 arm 3.
rq: [1]
overrides:
  retrieval:
    mode: hybrid_rerank
    reranker_model: cross-encoder/ms-marco-MiniLM-L-6-v2
```

Rules:

- A config file states **only what it changes**. If you find yourself copying the
  baseline and editing it, you are doing it wrong — that hides the manipulation.
- `rq:` lists which research questions the config serves. The sweep runner uses it.
- The resolved config is hashed (FR-CFG-04). Results carry the hash. **The hash is
  computed over the resolved parameter tree only** — the eight sections (`ingestion`,
  `chunking`, `embedding`, `store`, `retrieval`, `access_control`, `generation`,
  `evaluation`). The identifying metadata (`id`, `description`, `rq`) is deliberately
  excluded. Two consequences follow: editing a config's description or `rq` does **not**
  change its hash, so it cannot invalidate results already stamped with that hash; and two
  configs whose parameters resolve identically produce the **same** hash — which is the
  intended duplicate-arm check, surfacing an accidental copy that measures nothing new.
- `python -m chatbot.config diff C0-baseline C2-hybrid-rerank` prints exactly the
  manipulation. That output goes in the thesis methodology chapter verbatim.

---

## 2. Full parameter surface

Every key below is settable. Bold = varied in a shipped configuration. The rest are
held constant unless you deliberately open them up.

### 2.1 `ingestion`

| Key | Type | Default | Arms |
|---|---|---|---|
| `source_mode` | enum | `crawl` | `crawl` · `upload` · `both` |
| `max_pages` | int | 40 | — |
| `max_depth` | int | 3 | — |
| `request_delay_seconds` | float | 1.0 | — |
| `respect_robots` | bool | true | must stay true |
| **`interaction_probing`** | bool | true | `true` · `false` |
| **`workflow_extraction`** | bool | true | `true` · `false` |
| `blocked_control_patterns` | regex | conservative default | — |
| `browser_backend` | enum | `playwright` | `playwright` · `static` |

### 2.2 `chunking`

| Key | Type | Default | Arms |
|---|---|---|---|
| **`strategy`** | enum | `typed` | `fixed` · `recursive` · `typed` |
| **`size`** | int | 400 | 256 · 400 · 800 |
| `overlap` | int | 50 | 0 · 50 · 100 |
| `fixed_lines_per_chunk` | int | 3 | only for `fixed` |
| **`table_handling`** | enum | `header_repeat` | `split` · `header_repeat` · `atomic` |
| `heading_breadcrumb` | bool | true | `true` · `false` |
| `qa_pairing` | bool | true | `true` · `false` |
| `min_chunk_chars` | int | 40 | — |

### 2.3 `embedding`

| Key | Type | Default | Arms |
|---|---|---|---|
| **`model`** | str | `all-MiniLM-L6-v2` | + `BAAI/bge-small-en-v1.5`, `intfloat/e5-small-v2` |
| `dimensions` | int | 384 | derived; validated against the store |
| `normalize` | bool | true | — |
| `batch_size` | int | 32 | — |

### 2.4 `store`

Qdrant, cosine distance (`docs/08` OD-1). Held constant across every configuration —
the store is infrastructure, not an experimental variable.

| Key | Type | Default | Arms |
|---|---|---|---|
| `backend` | enum | `qdrant` | — |
| `host` / `port` | str / int | `localhost` / 6333 | — |
| `collection` | str | `sme_chatbot` | — |
| `distance` | enum | `cosine` | — |
| `payload_indexes` | list | `[domain_id, access_level, document_id, chunk_type]` | — |
| `allow_cosine_without_normalize` | bool | false | — |

**Why cosine and not L2.** `all-MiniLM-L6-v2` emits normalised vectors, for which L2 and
cosine rankings are equivalent — the nearest chunk by L2 is the highest-scoring chunk by
cosine. The metric is therefore not a meaningful experimental dimension here, and cosine
is chosen because it is Qdrant's idiomatic default and because similarity scores in
`[0, 1]` are directly readable in retrieval telemetry, where L2 distances are not.

If `embedding.normalize` is ever set false, this equivalence breaks and the distance
metric becomes a real choice. The config loader raises if `normalize: false` is combined
with `distance: cosine` without an explicit acknowledgement flag.

**Payload indexes are not optional.** Every query filters on `domain_id` and
`access_level`. Without payload indexes Qdrant scans the whole collection per query,
which makes `latency_ms` — a reported RQ1 result (`docs/03` §4.4) — measure index
absence rather than retrieval architecture.

### 2.5 `retrieval`

| Key | Type | Default | Arms |
|---|---|---|---|
| **`mode`** | enum | `dense` | `dense` · `hybrid` · `hybrid_rerank` |
| `top_k` | int | 5 | 3 · 5 · 10 |
| `candidate_k` | int | 30 | — |
| **`fusion`** | enum | `rrf` | `rrf` · `weighted` |
| `rrf_k` | int | 60 | — |
| `dense_weight` | float | 0.5 | only for `weighted` |
| `reranker_model` | str | null | — |
| `bm25_variant` | enum | `okapi` | `okapi` · `plus` |

### 2.6 `access_control`

| Key | Type | Default | Arms |
|---|---|---|---|
| **`strategy`** | enum | `prefilter` | `prefilter` · `postfilter` · `none` |
| `role_map` | dict | `{customer: [public], admin: [public, private]}` | — |
| `private_url_patterns` | list | `[/admin, /staff, /dashboard, /internal, /portal]` | — |
| `default_level` | enum | `public` | — |
| `fail_closed` | bool | true | **must stay true outside the harness** |

### 2.7 `generation`

| Key | Type | Default | Arms |
|---|---|---|---|
| **`model`** | str | `llama3.2` *(provisional — OD-3)* | base · fine-tuned |
| `base_url` | str | `http://localhost:11434/v1` | — |
| **`adapter`** | str | null | null · QLoRA adapter path |
| **`prompt_variant`** | enum | `strict_grounded` | `strict_grounded` · `permissive` |
| `temperature` | float | 0.0 | — |
| `max_tokens` | int | 512 | — |
| `history_turns` | int | 8 | — |
| `abstention_phrase` | str | `I do not have that information. Please contact us directly.` | — |

**`model` is provisional.** OD-3 (3B vs 7B) is unresolved, and the baseline needs a value
that validates today. `llama3.2` is the development default. Resolving OD-3 before Phase 5
costs nothing — no generation results exist until P5-8, and retrieval metrics (RQ1, RQ2,
RQ4) do not depend on the generator at all. See CLAUDE.md rule 8 on when the baseline
actually freezes.

**`abstention_phrase` is deliberately ASCII-only.** Detection is exact-substring
(`docs/06` §3), so an apostrophe or em-dash in the phrase makes matching hostage to how
the model renders Unicode punctuation — `don't` versus `don't` would silently score a
correct abstention as a failure. "do not" avoids the apostrophe; the full stop avoids the
dash. If you change the phrase, keep it free of characters that have a smart-quote
variant.

### 2.8 `evaluation`

| Key | Type | Default |
|---|---|---|
| `metrics` | list | `[precision_at_k, recall_at_k, mrr, hit_rate, latency_ms]` |
| `ragas_enabled` | bool | false |
| `relevance_granularity` | enum | `page` |
| `paired_test` | enum | `wilcoxon` |

---

## 3. Shipped configurations — the deliverable

Fifteen named configurations. Each isolates **one** manipulation from the baseline.

### Baseline

| ID | Manipulation | RQ | Notes |
|---|---|---|---|
| `C0-baseline` | — | — | Dense retrieval, typed chunking, prefilter ACL, base LLM. The reference point. Do not change (CLAUDE.md rule 8). |

### RQ1 — retrieval architecture

| ID | Manipulation | Notes |
|---|---|---|
| `C1-hybrid` | `retrieval.mode: hybrid` | Adds the BM25 arm |
| `C2-hybrid-rerank` | `retrieval.mode: hybrid_rerank` | Adds cross-encoder. The proposal's "full" pipeline |
| `C3-fusion-weighted` | `retrieval.fusion: weighted` | Tests whether RRF's tuning-free property costs accuracy |
| `C4-topk-10` | `retrieval.top_k: 10` | Recall/precision trade at fixed retrieval mode |

### Chunking — the arm the proposal did not plan, but Appendix A demands

| ID | Manipulation | Notes |
|---|---|---|
| `C5-chunk-fixed` | `chunking.strategy: fixed`, `fixed_lines_per_chunk: 3` | **Replicates the Appendix A condition.** The direct test of whether the observed table failure was chunking |
| `C6-chunk-recursive` | `chunking.strategy: recursive` | Standard RAG practice; the honest middle baseline |
| `C7-table-split` | `chunking.table_handling: split` | Isolates the table rule alone, holding everything else typed |
| `C8-no-breadcrumb` | `chunking.heading_breadcrumb: false` | Isolates the breadcrumb's contribution to both retrieval arms |

### Supervisor's hypothesis — the ablation nobody in the literature has run

| ID | Manipulation | Notes |
|---|---|---|
| `C9-no-workflows` | `ingestion.workflow_extraction: false` | Does LLM workflow synthesis beat chunking the prose it was derived from? |
| `C10-no-interaction` | `ingestion.interaction_probing: false` | Does clicking buttons recover content that passive scraping misses? |

### RQ2 — access control

| ID | Manipulation | Notes |
|---|---|---|
| `C11-acl-postfilter` | `access_control.strategy: postfilter` | ARBITER-style comparison (Lorenzo et al., 2025) |
| `C12-acl-none` | `access_control.strategy: none` | Control: establishes the leakage ceiling. **Harness-only** |

### RQ3 — fine-tuning

| ID | Manipulation | Notes |
|---|---|---|
| `C13-finetuned` | `generation.adapter: <qlora path>` | Best RQ1 config + tuned generator |
| `C14-prompt-permissive` | `generation.prompt_variant: permissive` | Isolates how much of the grounding comes from prompting vs. retrieval |

### RQ4 — generalisation

RQ4 is not a configuration. It is **every configuration above, run against both
`domain_id`s**, with results grouped by domain. Nothing extra to build; it falls out of
FR-EVAL-08.

---

## 4. Design decisions to defend in the thesis

Write these up as methodology, not implementation detail. Each is a choice with a
defensible alternative, which is exactly what a marker looks for.

### 4.1 One factor at a time, not factorial

Fifteen configurations, not the ~10,000-cell full factorial the parameter surface allows.
With 30–50 questions per domain, a factorial design is both computationally infeasible
and statistically uninterpretable. OFAT from a fixed baseline gives clean attribution at
the cost of missing interaction effects — state that limitation explicitly in chapter 5
rather than letting a marker find it.

### 4.2 RRF as the default fusion

Cosine similarity and BM25 scores are on incomparable scales. Weighted fusion needs a
normalisation constant tuned per corpus — precisely the tuning an SME has nobody to
perform. RRF uses rank position only, so it transfers to a new site without
recalibration. That property is directly relevant to RQ4, and `C3-fusion-weighted`
tests whether it costs accuracy to have it.

### 4.3 Pre-filtering as the default access strategy

`prefilter` makes leakage impossible by construction; `postfilter` makes it unlikely.
ARBITER reports 85% accuracy / 89% F1 *because* it classifies after retrieval. Filtering
on indexed metadata before scoring trades that residual risk for a dependency on correct
labelling at ingest — the hard problem moves from retrieval to ingestion. `C11` and `C12`
make that trade measurable rather than merely asserted. This is the strongest
contribution claim available for RQ2.

The guarantee is only structural if the filter is applied **inside** the search, not
around it. Under `prefilter`, the permitted `access_level` set is passed to Qdrant as a
payload filter on the same call that does the vector search, so an impermissible chunk is
never scored and never enters the candidate set. Retrieving `candidate_k` chunks and then
discarding the private ones is a different mechanism with a different failure mode — it
is what `C11-acl-postfilter` implements, and the distinction is the whole point of the
comparison. The BM25 arm has no server-side equivalent, so it masks disallowed documents
before ranking rather than after, which preserves the same property: the top-*n* is the
top-*n* of what this role can see, not the top-*n* overall with holes in it.

### 4.4 Latency is a result, not an implementation note

Reranking costs a cross-encoder forward pass per candidate. On the target hardware that
is not free. An SME choosing between `C0` and `C2` needs the quality gain *and* the
latency cost. Report both in the RQ1 table. This is what makes the contribution
SME-specific rather than a generic RAG benchmark.

### 4.5 Chunking is an experimental arm

The proposal treats chunking as a fixed implementation detail. Appendix A's one
documented failure was a chunking failure. Configs `C5`–`C8` correct that omission. If
the effect size of `C0` vs `C5` exceeds `C0` vs `C2`, the honest headline finding of
this thesis is *"chunking strategy dominates retrieval architecture at SME scale"* —
which would be a more useful contribution than confirming that reranking helps.

---

## 5. Adding a configuration

1. Create `configs/<ID>-<slug>.yaml` with `extends`, `rq`, `description`, `overrides`.
2. Change **one** thing. If you need two, that is two configs, or say explicitly in the
   description why they are inseparable.
3. Add it to the relevant list in `configs/sweeps/rq<N>.yaml`.
4. Run `python -m chatbot.config diff C0-baseline <ID>` and paste the output into the
   description. If the diff surprises you, the merge is wrong.
5. Add a row to §3 above in the same commit.
