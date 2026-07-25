# CLAUDE.md

Read this first. It governs every session in this repository.

## What this repository is

A **research artefact**, not a product. It is the prototype for a UTS Honours thesis
(Hai Nam Truong, supervised by Yining Hu): *AI Chatbot for Answering Questions Using an
Organization's Internal Data*.

The thesis answers four research questions by **running the same test set through
different pipeline configurations and comparing the numbers**. That sentence is the
whole design constraint. Every decision in this codebase follows from it.

**The deliverable is not a chatbot. The deliverable is a set of switchable RAG
configurations plus a harness that evaluates them.** A chatbot that works beautifully
but cannot be reconfigured and re-measured has failed the brief.

## The four research questions

| RQ | Question | Varied by |
|---|---|---|
| RQ1 | Does hybrid retrieval + reranking beat vector search alone? | `retrieval.mode` |
| RQ2 | What strategies let one system serve public and private users? | `access_control.strategy`, `role` |
| RQ3 | Does fine-tuning add measurable value on top of RAG? | `generation.model` / `generation.adapter` |
| RQ4 | Does pipeline performance generalise across businesses? | `domain_id` |

Full requirements: `docs/02-requirements.md`. Every requirement carries an ID
(`FR-RET-03`) and traces to an RQ. When you implement something, reference the ID in
the commit message.

## Before you write code

Read the doc that owns the area you are touching. Do not infer the design from
neighbouring code — several conventions here are deliberate and non-obvious.

| Touching | Read first |
|---|---|
| Anything at all | `docs/01-context-and-scope.md` |
| Config, experiment arms | `docs/03-configuration-matrix.md` |
| Module structure, interfaces | `docs/04-architecture.md` |
| Payloads, CSV schemas, API bodies | `docs/05-data-contracts.md` |
| Metrics, harness, scoring | `docs/06-evaluation-protocol.md` |
| What to build next | `docs/07-build-plan.md` |
| Anything that feels ambiguous | `docs/08-open-decisions.md` |

## Hard rules

These are not style preferences. Breaking them invalidates experimental results.

1. **No hardcoded pipeline parameters.** Every value that could differ between
   configurations lives in a config file and is read through the config object. If you
   type `chunk_size=400` anywhere outside `configs/`, that is a bug.

2. **Fail loud on unknown config.** Never silently default. An unrecognised
   `retrieval.mode` raises; it does not fall back to dense. A run that quietly measured
   something other than what it claimed is worse than a crashed run.

3. **Determinism by default.** `temperature: 0.0` for all evaluation runs. Seed every
   stochastic operation. The same config against the same corpus must produce the same
   numbers on a re-run — if it does not, RQ1 is unmeasurable.

4. **Access control fails closed.** If role scoping cannot be resolved, return nothing.
   Never return a chunk whose `access_level` is not explicitly permitted for the
   requesting role. See `docs/05-data-contracts.md` §3.

5. **Never invent an evaluation metric.** The metrics are defined in
   `docs/06-evaluation-protocol.md`. If a metric seems missing, raise it as an open
   decision rather than adding one.

6. **The crawler is a guest on someone else's website.** It honours `robots.txt`,
   rate-limits, and never activates a control that could submit, purchase, delete, or
   authenticate. See `FR-CRAWL-05`.

7. **Results are immutable and stamped.** Every results row carries the `config_id` and
   the config hash that produced it. Never edit a results file by hand.

8. **Do not change baseline config values.** `configs/C0-baseline.yaml` is the reference
   point every other configuration is measured against. Changing it silently invalidates
   every comparison already run. If it must change, that is an open decision, and all
   affected results are re-run.

   **The rule binds from the first recorded result, not from file creation.** Before any
   run exists in `results/`, editing the baseline is free — nothing has been measured
   against it yet. After the first result, any change is an open decision plus a re-run.
   So a value left provisional in Phase 0 (see `docs/08` OD-3) can still be settled
   cheaply, provided it is settled before the sweep that depends on it. Check `results/`
   before assuming a change is costly, and record the change in `docs/08` either way.

## Commands

```bash
make install          # deps + playwright chromium
make services         # docker: vector store, redis, postgres
make dev              # uvicorn with reload
make test             # pytest, no network
make lint             # ruff + mypy
make crawl CONFIG=C0-baseline DOMAIN=domain-a URL=https://...
make eval CONFIG=C0-baseline
make sweep RQ=1       # every configuration for one research question
```

## Definition of done

A task is done when all of these hold:

- [ ] Implements a numbered requirement from `docs/02-requirements.md`
- [ ] All parameters routed through config; nothing hardcoded
- [ ] Unit tests pass with no network access
- [ ] Type hints on public functions; `make lint` clean
- [ ] Docstring states *why*, not what — the what is in the code
- [ ] If it changes a data contract, `docs/05-data-contracts.md` updated in the same commit
- [ ] If it changes measured behaviour, affected results flagged for re-run

## Working style

- **Ask before assuming.** This is research code; a wrong assumption produces a plausible
  number that is wrong, which is the worst possible failure mode. If a spec is ambiguous,
  stop and add it to `docs/08-open-decisions.md` rather than picking.
- **Small commits, one requirement each.** The thesis needs an auditable trail of what
  changed when.
- **Comment the non-obvious choices.** Future-you writing chapter 4 will need to explain
  why RRF and not weighted fusion. Write that down where the decision lives.
- **Prefer boring.** This runs on one consumer-grade machine with ≤16GB VRAM. Every
  dependency and every clever abstraction is a thing that can break in week 11.
- **Each build phase lands on its own branch (`feature/phase-N-name`) and merges to main
  only after the phase's review gate has passed.** `main` is the reviewed trunk, never the
  working branch.