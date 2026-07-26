# Documentation index

Read in order on first pass. After that, `CLAUDE.md` routes you to the right doc.

| Doc | Owns |
|---|---|
| [`../CLAUDE.md`](../CLAUDE.md) | Session entry point, hard rules, definition of done |
| [`01-context-and-scope.md`](01-context-and-scope.md) | Research framing, constraints, scope boundary, glossary |
| [`02-requirements.md`](02-requirements.md) | Numbered requirements traced to research questions |
| [`03-configuration-matrix.md`](03-configuration-matrix.md) | **The deliverable.** Every switchable dimension and the 15 shipped configurations |
| [`04-architecture.md`](04-architecture.md) | Repo tree, strategy registries, data flow, dependency rules |
| [`05-data-contracts.md`](05-data-contracts.md) | Chunk payload, test set CSV, results schemas, API bodies |
| [`06-evaluation-protocol.md`](06-evaluation-protocol.md) | Metric definitions, scoring rules, statistical procedure |
| [`07-build-plan.md`](07-build-plan.md) | 13-week phased plan, acceptance criteria, compute budget, risks |
| [`08-open-decisions.md`](08-open-decisions.md) | Unresolved choices, plus the Decided audit trail. **Read before assuming anything.** |
| [`09-research-log.md`](09-research-log.md) | Dated, append-only record of experiments run and what they taught (the *why* behind the pipeline's shape) |
| [`proposal-amendment-OD1.md`](proposal-amendment-OD1.md) | Replacement text for the proposal's methodology section following the Qdrant decision |

## The one-paragraph version

The deliverable is not a chatbot. It is a set of named, switchable RAG configurations
plus a harness that runs the same golden test set through each and produces comparable
numbers. Every pipeline parameter lives in a YAML config; every experimental arm is one
config file changing one thing. A chatbot that answers well but cannot be reconfigured
and re-measured has failed the brief.
