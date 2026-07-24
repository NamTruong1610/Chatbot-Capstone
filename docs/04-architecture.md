# 04 — Architecture

## 1. The organising principle

Every dimension in `docs/03-configuration-matrix.md` maps to a **strategy interface with
a registry**. Adding an experimental arm means writing one class and registering it — it
never means adding an `if` to a pipeline function.

```
config value  →  registry lookup  →  strategy instance  →  pipeline stage
"typed"          CHUNKERS["typed"]    TypedChunker(cfg)     chunk()
```

If you find yourself branching on a config value inside a pipeline stage, stop. That
branch belongs in a strategy class. This is the single most important structural rule in
the repo, because it is what keeps the configuration matrix honest: a reader of
`configs/C5-chunk-fixed.yaml` can see the entire manipulation without reading code.

## 2. Repository tree

```
.
├── CLAUDE.md
├── Makefile
├── pyproject.toml
├── .env.example
├── docs/                          # this documentation set
│
├── configs/
│   ├── C0-baseline.yaml           # the root config — see CLAUDE.md rule 8
│   ├── C1-hybrid.yaml
│   ├── ...                        # C2..C14, one manipulation each
│   └── sweeps/
│       ├── rq1.yaml               # ordered list of config ids
│       ├── rq2.yaml
│       ├── rq3.yaml
│       └── chunking.yaml
│
├── prompts/
│   ├── strict_grounded.md
│   ├── permissive.md
│   └── workflow_extraction.md
│
├── src/chatbot/
│   ├── config/
│   │   ├── schema.py              # pydantic models, one per config section
│   │   ├── loader.py              # extends-resolution, deep merge, validation, hashing
│   │   └── __main__.py            # `show` / `diff` / `validate` CLI
│   │
│   ├── ingestion/
│   │   ├── crawler/
│   │   │   ├── base.py            # Crawler protocol
│   │   │   ├── playwright.py      # JS-rendering backend
│   │   │   ├── static.py          # requests + bs4 fallback
│   │   │   ├── affordances.py     # form/table/control extraction
│   │   │   └── safety.py          # blocklist, robots, rate limiting
│   │   ├── workflow/
│   │   │   ├── digest.py          # bounded page compression (FR-WF-01)
│   │   │   └── extractor.py       # two-pass LLM extraction
│   │   ├── chunking/
│   │   │   ├── base.py            # Chunker protocol + CHUNKERS registry
│   │   │   ├── fixed.py           # Appendix A replication
│   │   │   ├── recursive.py
│   │   │   └── typed.py           # per-content-type rules
│   │   ├── access.py              # access_level assignment (FR-ACL-02)
│   │   └── pipeline.py            # orchestration: crawl → extract → chunk → index
│   │
│   ├── retrieval/
│   │   ├── base.py                # Retriever protocol + RETRIEVERS registry
│   │   ├── dense.py
│   │   ├── sparse.py              # BM25
│   │   ├── hybrid.py              # composes dense + sparse + fusion
│   │   ├── fusion.py              # rrf | weighted
│   │   ├── rerank.py              # cross-encoder
│   │   └── acl.py                 # prefilter | postfilter | none
│   │
│   ├── generation/
│   │   ├── client.py              # LLM transport
│   │   ├── prompts.py             # template loading from prompts/
│   │   └── service.py             # context assembly, citation, abstention
│   │
│   ├── store/
│   │   ├── vector.py              # Qdrant adapter — the ONLY module that
│   │   │                          #   imports qdrant_client (FR-STORE-01)
│   │   ├── session.py             # Redis
│   │   └── summary.py             # Postgres
│   │
│   ├── api/
│   │   ├── main.py                # FastAPI app, lifespan, middleware
│   │   ├── routes/                # chat, ingest, crawl, admin
│   │   ├── schemas/               # request/response models
│   │   └── deps.py                # config injection
│   │
│   └── evaluation/
│       ├── testset.py             # golden test set loading + validation
│       ├── metrics.py             # pure functions, no I/O
│       ├── runner.py              # single-config run
│       ├── sweep.py               # multi-config orchestration
│       ├── compare.py             # paired tests, effect sizes
│       └── report.py              # grouped summaries, tables
│
├── scripts/
│   ├── build_testset.py           # scaffold Q&A pairs from a crawl for manual editing
│   └── finetune_qlora.py          # RQ3
│
├── data/                          # gitignored except .gitkeep
│   ├── corpora/<domain_id>/       # raw crawl JSON — never regenerate, never edit
│   └── testsets/<domain_id>.csv
│
├── results/                       # append-only, timestamped
│   └── <timestamp>-<config_id>/
│
└── tests/
    ├── unit/                      # no network, no services
    ├── integration/               # requires docker services
    └── fixtures/                  # frozen crawl JSON for deterministic tests
```

## 3. Core interfaces

Written as protocols. Every implementation takes the resolved config in its constructor
and nothing else — no globals, no env reads (FR-CFG-05).

```python
# ingestion/chunking/base.py
class Chunker(Protocol):
    def __init__(self, cfg: ChunkingConfig) -> None: ...
    def chunk_page(self, page: CrawledPage) -> list[Chunk]: ...
    def chunk_workflow(self, wf: Workflow) -> list[Chunk]: ...

CHUNKERS: dict[str, type[Chunker]] = {}

def register_chunker(name: str):
    def deco(cls): CHUNKERS[name] = cls; return cls
    return deco
```

```python
# retrieval/base.py
class Retriever(Protocol):
    def __init__(self, cfg: RetrievalConfig, store: VectorStore) -> None: ...
    async def retrieve(
        self, query: str, domain_id: str, allowed_levels: set[str]
    ) -> RetrievalResult: ...

RETRIEVERS: dict[str, type[Retriever]] = {}
```

```python
# retrieval/acl.py
class AccessStrategy(Protocol):
    def levels_for(self, role: str) -> set[str]: ...
    def prefilter(self) -> bool: ...          # apply before scoring?
    def enforce(self, chunks: list[RetrievedChunk], role: str) -> tuple[list, int]: ...
    # returns (permitted chunks, leaked count)
```

Note that `AccessStrategy` exposes both a pre-filter hook and a post-hoc `enforce`.
`prefilter` uses the first and asserts on the second; `postfilter` skips the first and
relies on the second; `none` does neither. One interface, three arms, no branching in
the retriever.

## 4. Data flow

### Ingestion

```
root URL
  ↓ Crawler (playwright | static)
CrawledPage[]  ──────────────────────────→ data/corpora/<domain>/crawl_<ts>.json
  ↓                                          (FR-CRAWL-09: raw, immutable, first)
  ├→ WorkflowExtractor          [if ingestion.workflow_extraction]
  │    ↓ digest (bounded)
  │    ↓ pass 1: page → candidates
  │    ↓ pass 2: candidates → merged workflows
  │  Workflow[]
  ↓
Chunker (CHUNKERS[chunking.strategy])
  ↓
Chunk[] + access_level assignment
  ↓
Embedder (embedding.model)
  ↓
VectorStore.upsert  +  IndexFingerprint written
```

### Query

```
question + domain_id + role
  ↓
AccessStrategy.levels_for(role)
  ↓
Retriever (RETRIEVERS[retrieval.mode])
  ├ dense arm   → Qdrant query_points(vector, filter=domain_id + access_level)
  │                the filter rides along with the search; impermissible chunks
  │                are never scored          [if strategy.prefilter()]
  ├ sparse arm  → BM25 over the domain corpus, disallowed docs masked before
  │                ranking, not after        [if strategy.prefilter()]
  ├ fusion      (rrf | weighted)
  └ rerank      (if mode == hybrid_rerank)
  ↓
AccessStrategy.enforce → (chunks, leaked_count)
  ↓
GenerationService: prompt template + numbered context + history
  ↓
answer + sources + telemetry
```

## 5. The index fingerprint

FR-EVAL-11 exists because the most dangerous failure in this project is silent: running
a `typed`-chunking evaluation against an index that was built with `fixed` chunking. The
numbers look plausible and mean nothing.

Every ingest writes a fingerprint alongside the vectors:

```json
{
  "domain_id": "domain-a",
  "config_id": "C0-baseline",
  "chunking_hash": "…",
  "embedding_model": "all-MiniLM-L6-v2",
  "embedding_dimensions": 384,
  "crawl_manifest": "crawl_20260801T0912.json",
  "chunk_count": 1284,
  "ingested_at": "…"
}
```

The evaluation runner compares the fingerprint against the config under test. Mismatch on
`chunking_hash` or `embedding_model` → **refuse to run**, with a message naming which
config the index was built with and what to re-ingest. Do not add a `--force` flag.

Practical consequence for the build plan: chunking and embedding arms (`C5`–`C8`,
embedding variants) each require their own ingest pass. Budget for it — see
`docs/07-build-plan.md` §4.

## 6. Dependency rules

Enforce with import-linter in CI.

```
config     ← imported by everything, imports nothing internal
store      ← imports config only
ingestion  ← imports config, store
retrieval  ← imports config, store
generation ← imports config, retrieval
api        ← imports all of the above
evaluation ← imports all of the above
```

- `evaluation` may import pipeline code. Pipeline code may **never** import `evaluation`.
- `metrics.py` is pure functions over lists and dicts — no I/O, no config, no imports from
  the rest of the package. It must be testable in isolation, because every number in the
  thesis passes through it.

## 7. Extension points

| To add | Do this |
|---|---|
| A chunking strategy | Subclass `Chunker`, `@register_chunker("name")`, add enum value to `ChunkingConfig.strategy` |
| A retrieval mode | Subclass `Retriever`, register, extend the enum |
| A fusion method | Add a function to `fusion.py`, register in `FUSIONS` |
| An access strategy | Subclass `AccessStrategy`, register |
| A prompt variant | Add `prompts/<name>.md`, extend the enum |
| A metric | **Don't.** Raise it in `docs/08-open-decisions.md` first (CLAUDE.md rule 5) |

## 8. What is deliberately not here

- **No LangChain orchestration.** Only a text splitter is used, and only inside
  `recursive.py`. The proposal names LangChain as the orchestration framework; see
  `docs/08` OD-2 for the decision to revisit. Orchestration frameworks obscure exactly
  the parameters this project needs to vary and report.
- **No async job queue.** Crawls block. Wrong for production, right for a study where
  runs must be reproducible and timed.
- **No caching layer between query and retrieval.** A cache would make latency
  measurements meaningless.
- **No abstraction over the LLM provider beyond a base URL.** Ollama's OpenAI-compatible
  endpoint covers both local and hosted models.
