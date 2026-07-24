# 01 — Context and Scope

## 1. The problem

SMEs want customer-service chatbots. Existing RAG frameworks that work are validated in
resource-rich settings: legal compliance systems (Hu et al., 2026), regulated finance
(Hiriyanna & Zhao, 2025), large enterprises with dedicated AI teams (Akkiraju et al.,
2024). Gao et al. (2024) note advanced RAG needs expertise smaller organisations lack;
Lübbers et al. (2025) identify infrastructure cost, engineering complexity and security
as the primary barriers to SME adoption.

No existing study systematically examines multi-layered RAG design *under SME
constraints* — limited resources, smaller knowledge bases, no dedicated AI staff. That
gap is what this project addresses.

## 2. Methodology

Design science (Hevner et al., 2004): knowledge is produced by building an artefact and
evaluating it rigorously. The artefact is the configurable pipeline. The evaluation is
the configuration sweep.

The practical consequence for this codebase: **the artefact must be instrumented**.
A pipeline that produces good answers but cannot report precision@k per configuration is
not an artefact for this methodology — it is a demo.

## 3. Supervisor direction

Two pieces of direction from Yining shape the ingestion layer, and both go beyond what
the proposal's methodology section describes:

> "Rather than having a document supplied to the chatbot, can we get the chatbot to
> navigate itself through all the pages/js available from the frontend and extract the
> business workflow"

> "One challenge would be how can an AI chatbot understand the business workflows from
> content on the website; perhaps it needs to identify main features and then click all
> the buttons/get the js to understand what each button does"

> "If you give the entire website content to an AI, it will likely not accept everything
> because of the token limit; and hence you need to chunk your content — and what are the
> rules for chunking? are there multiple steps involved in one workflow?"

This makes **autonomous site ingestion** primary and document upload secondary, and makes
**chunking strategy a first-class experimental variable** rather than a fixed
implementation detail. See `FR-CRAWL-*`, `FR-WF-*`, `FR-CHUNK-*`.

## 4. Hard constraints

| Constraint | Value | Consequence |
|---|---|---|
| Compute | One consumer-grade machine, ≤16GB VRAM | 7B models max, QLoRA not full fine-tune, no cluster |
| Timeline | 13 weeks, 27 Jul – 23 Oct 2026 | Scope ruthlessly; see `docs/07-build-plan.md` |
| Test set size | 30–50 Q&A pairs per domain | Underpowered for full factorial — see §6 below |
| Corpus | Public web content, 2 SME domains, distinct industries | Scraping permission required per domain |
| Team | One student, part-time | Prefer boring, well-trodden dependencies |

## 5. Evidence the design must account for

The proposal's Appendix A ran a preliminary retrieval test: MiniLM embeddings, FAISS,
fixed 3-line chunks, 206 chunks, 5 queries. Findings:

- Most top-ranked chunks contained the correct answer (L2 0.2295–0.6588)
- **A faculty date table was split across chunk boundaries and fell outside top-k**
- One query returned an outright wrong answer

This is a **chunking failure, not a retrieval-method failure**. It is the single
strongest piece of local evidence the project has, and it means chunking strategy must
be an experimental arm, not a constant. Any configuration matrix that holds chunking
fixed cannot explain the one failure the project has already observed.

## 6. Statistical reality — read this before designing experiments

With 30–50 questions per domain, this study can detect large effects, not small ones.
Consequences that must shape the harness:

- **One factor at a time (OFAT) from a baseline**, not full factorial. A full factorial
  over the matrix in `docs/03` is thousands of runs and would be uninterpretable at this n.
- **Report per-question results, not just means.** With n=40 the mean hides everything.
  Paired comparisons (same question, two configs) are the useful unit.
- **Report effect sizes and CIs, not just point estimates.** A 3-point precision@5
  difference on n=40 is noise.
- **A null result is a valid finding.** The proposal already commits to this for RQ3.
  It applies equally to RQ1: "reranking did not measurably help at SME scale" is a real
  contribution given that Hu et al. (2026) report a 7.38-point drop without it.

## 7. Scope

**In scope**
- Configurable ingestion (crawl-first, upload secondary)
- Configurable chunking, embedding, retrieval, access control, generation
- Evaluation harness producing per-configuration comparison tables
- Two-domain corpus + golden test sets
- Embeddable frontend widget sufficient to demonstrate integration
- QLoRA fine-tuning for RQ3

**Out of scope**
- Production hardening, autoscaling, multi-region, SLAs
- Real customer data of any kind — public web content only
- Human evaluation studies (no ethics approval; RAGAS LLM-as-judge substitutes)
- More than two business domains
- Multi-turn conversational reasoning beyond session history + summary
- Any commercial deployment

## 8. Glossary

| Term | Meaning here |
|---|---|
| **Configuration** | A complete, named, versioned set of pipeline parameters. The unit of experiment. |
| **Arm** | One value of one varied dimension (e.g. `retrieval.mode=hybrid`). |
| **Baseline** | `C0-baseline` — the reference configuration all others are compared against. |
| **Affordance** | Something a user can *do* on a page: a form, a button, a link. Distinct from page text. |
| **Workflow** | An ordered multi-step business procedure inferred from affordances. |
| **Chunk type** | `workflow` / `table` / `qa` / `prose` — determines the chunking rule applied. |
| **Access level** | `public` / `private` — the label on a chunk that role scoping filters against. |
| **Role** | `customer` / `admin` — the requesting user's access class. |
| **Golden test set** | Manually constructed Q&A pairs with known source pages. Ground truth. |
| **Domain** | One SME business. `domain_id` partitions the shared vector collection. Note: overloaded — "domain" also means industry in RQ4. Prefer `domain_id` for the former. |
