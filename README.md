# Configurable RAG Chatbot for SME Customer Support

A retrieval-augmented generation (RAG) chatbot that answers questions about a small
business from **that business's own website**, grounds every answer in the crawled
content, and enforces role-based access so private staff material never reaches
customers — running entirely on local, open-weight models.

This repository is the artefact for a UTS Honours Engineering Capstone
(Hai Nam Truong, supervised by Prof. Yining Hu). **The deliverable is not a chatbot.
It is a set of named, switchable RAG configurations plus a harness that runs the same
fixed test set through each and produces comparable numbers.** Every pipeline parameter
lives in a YAML config; every experimental arm is one config file changing one thing.

> Start with [`CLAUDE.md`](CLAUDE.md) and [`docs/README.md`](docs/README.md). The hard
> rules (no hardcoded parameters, fail loud, determinism, access fails closed, immutable
> stamped results) are in `CLAUDE.md` and govern every change.

## The four research questions

| RQ | Question | Varied by |
|---|---|---|
| RQ1 | Does hybrid retrieval + reranking beat vector search alone? | `retrieval.mode` (C0 / C1 / C2) |
| RQ2 | How can one system serve public and private users? | `access_control.strategy`, `role` |
| RQ3 | Which generation model × prompt strictness serves best? | `generation.model`, `generation.prompt_variant` |
| RQ4 | Does performance generalise across businesses? | `domain_id` |

The study is evaluated on three real businesses, each a free-form `domain_id`:
`wyatt-edu` (vocational training, table-heavy), `austral-mfg` (manufacturing, prose-heavy),
and `animal-hospitals` (a veterinary group, mixed). Their hand-authored test sets live in
`tests/data/`.

## Prerequisites

- **Python 3.11+** (the lint config targets 3.12 to match the runtime venv)
- **Docker** (for the backing services: Postgres for conversation history, Qdrant for vectors)
- **[Ollama](https://ollama.com)** running locally for generation and workflow extraction,
  with the models the configs reference pulled:
  ```bash
  ollama pull llama3.2       # 3B — baseline / 3B generation arms
  ollama pull llama3.1:8b    # 8B — larger generation arms
  ```
  The generation endpoint is OpenAI-compatible at `http://localhost:11434/v1` (set in the configs).
- A consumer GPU with **≤16 GB VRAM** is enough; CPU works but is slower.

## Install

```bash
make install        # create .venv, install the package + dev extras, install Playwright Chromium
```

If Chromium is provisioned externally, skip its download and point `CHATBOT_CHROMIUM_PATH`
at the binary.

## Run the backing services

```bash
make services       # docker compose up -d  →  postgres:16, qdrant:v1.11.0
```

Conversation history needs Postgres; point `CHATBOT_POSTGRES_DSN` at it (see
`docker-compose.yml` for credentials). Retrieval/ingest needs Qdrant.

## Crawl and ingest a business

The chatbot serves one or more businesses, each in its own partition keyed by a free-form
`domain_id`. Two ways to get a business's content into the index:

**A. Through the API (crawl + ingest live).** Start the server and post the site:

```bash
make dev            # uvicorn chatbot.api.main:create_app --factory --reload
curl -X POST localhost:8000/api/crawl/site -H 'Content-Type: application/json' -d '{
  "domain_id": "wyatt-edu",
  "root_url":  "https://wyatt.nsw.edu.au",
  "max_pages": 40,
  "max_depth": 3
}'
```

The crawler honours `robots.txt`, rate-limits, and never activates a control that could
submit, purchase, delete or authenticate (`FR-CRAWL-05`). It persists the crawl JSON under
`data/corpora/<domain_id>/` and ingests it in one pass.

**B. From a saved crawl, via the CLI** (reproducible, no live site needed):

```bash
python -m chatbot.evaluation ingest \
  --config C0-baseline --domain wyatt-edu \
  --root-url https://wyatt.nsw.edu.au \
  --corpus data/corpora/wyatt-edu/crawl_<timestamp>.json
# add private staff content alongside the public set (used for the RQ2 access test):
#   --private-corpus tests/data/animal_hospitals_private_staff.json
```

Ingesting with a different chunking/embedding config rebuilds that config's own index; the
**fingerprint guard** refuses to serve or score an index a config did not build.

## Evaluate

All evaluation runs through one CLI. Each writes a stamped results file (see
*Reproducibility* below) and prints a per-case readout plus an aggregate.

```bash
# Retrieval scoring (page-level + answer-span metrics) — RQ1
python -m chatbot.evaluation run \
  --config C0-baseline --domain wyatt-edu --testset tests/data/wyatt_rq1.csv

# Full retrieve→generate pipeline, scored for grounding + refusal — RQ3
python -m chatbot.evaluation chat-eval \
  --config C-gen-8b-strict --domain wyatt-edu --testset tests/data/wyatt_rq1.csv

# Access-control isolation: run every case as customer AND staff, report leaks — RQ2
python -m chatbot.evaluation acl-eval \
  --config C0-baseline --domain animal-hospitals \
  --testset tests/data/animal_hospitals_access.csv

# Debug readout: dense retrieval top-k for one question (no scoring)
python -m chatbot.evaluation query \
  --config C0-baseline --domain wyatt-edu "How much is the Diploma of Business?"
```

**RQ4 (portability)** is the same `run` command pointed at another domain, unchanged:

```bash
python -m chatbot.evaluation run --config C0-baseline --domain austral-mfg \
  --testset tests/data/austral_rq4.csv
python -m chatbot.evaluation run --config C0-baseline --domain animal-hospitals \
  --testset tests/data/animal_hospitals_rq.csv
```

The test sets (hand-authored, in `tests/data/`):

| Domain | Retrieval / generation | Access control | Private corpus |
|---|---|---|---|
| `wyatt-edu` | `wyatt_rq1.csv` (100) | `wyatt_rq2_access.csv` (12) | — |
| `austral-mfg` | `austral_rq4.csv` (80) | — | — |
| `animal-hospitals` | `animal_hospitals_rq.csv` (92) | `animal_hospitals_access.csv` (16) | `animal_hospitals_private_staff.json` |

Metric definitions and scoring rules live in
[`docs/06-evaluation-protocol.md`](docs/06-evaluation-protocol.md); the automatic metrics
are a fast regression signal, and headline numbers are confirmed by reading the answers
(the methodological point of the thesis).

## Inspect and compare configurations

```bash
python -m chatbot.config show C0-baseline           # fully resolved config + its hash
python -m chatbot.config diff C0-baseline C1-hybrid  # only the keys that differ
python -m chatbot.config validate C2-hybrid-rerank   # load + validate, fail loud on error
```

## The configurations

`configs/C0-baseline.yaml` is the reference every other config is measured against; it
carries the complete parameter tree and must not change once results exist (`CLAUDE.md`
rule 8). Every other config overrides only what it manipulates.

| Config | What it changes | RQ |
|---|---|---|
| `C0-baseline` | dense retrieval, typed chunking, prefilter ACL, 3B strict prompt | reference |
| `C1-hybrid` | hybrid retrieval (dense + BM25, RRF fusion) | RQ1 |
| `C2-hybrid-rerank` | hybrid + cross-encoder reranking | RQ1 |
| `C-gen-3b-permissive` | 3B model, permissive prompt | RQ3 |
| `C-gen-8b-strict` | 8B model, strict grounded prompt | RQ3 |
| `C-gen-8b-permissive` | 8B model, permissive prompt | RQ3 |
| `C5-chunk-fixed` | fixed-size chunking | RQ1 (chunking) |
| `C6-chunk-recursive` | recursive chunking | RQ1 (chunking) |
| `C7-table-split` | split tables instead of keeping them whole | RQ1 (chunking) |
| `C8-no-breadcrumb` | drop heading breadcrumbs from chunks | RQ1 (chunking) |
| `C9-no-workflows` | disable workflow extraction at ingest | ablation |

## Reproducibility

- **Determinism by default.** Evaluation runs at `temperature: 0` with seeded stochastic
  operations, so the same config against the same index produces the same numbers.
- **Every results file is stamped** with the `config_id`, the config hash, the git SHA, the
  domain, and the resolved config, so any reported number maps back to the exact settings
  and code that produced it. Results are append-only; never edit a results file by hand.
  (`results/` is gitignored — runs live locally; the dated findings are recorded in
  `docs/09-research-log.md`.)
- **Fingerprint guard.** The pipeline refuses to serve or score an index that a different
  config (chunking/embedding) built, rather than silently measuring the wrong thing.

## Tests and linting

```bash
make test           # pytest — no network, no services
make lint           # ruff + mypy
```

## Repository layout

```
src/chatbot/        config, ingestion (crawler + chunking + workflow), store,
                    retrieval, generation, pipeline, api, evaluation
configs/            the switchable configurations (C0 … C9, C-gen-*)
tests/              unit tests (offline) and the hand-authored test sets under tests/data/
docs/               design docs 01–09 (read docs/README.md first)
data/corpora/       crawled corpora (generated; not committed)
results/            stamped evaluation outputs (generated; gitignored)
```

## Documentation

The `docs/` tree is the authoritative design record — context and scope (`01`),
requirements (`02`), the configuration matrix (`03`), architecture (`04`), data contracts
(`05`), the evaluation protocol (`06`), the build plan (`07`), open decisions (`08`), and
the dated research log (`09`). `CLAUDE.md` routes to the right doc for any area you touch.
