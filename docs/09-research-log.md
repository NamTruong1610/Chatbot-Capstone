# 09 — Research Log

Dated, append-only record of experiments actually run and what they taught. Distinct from
`docs/08-open-decisions.md` (pending decisions) and the results files (`results/`, machine
output): this is the human narrative a marker and future-you read to understand *why* the
pipeline is shaped the way it is. Newest entry first. Never edit a past entry — correct it
with a new one.

---

## 2026-07-25 — Thin vertical slice, Wyatt (dense / typed chunking / MiniLM / C0-baseline)

First end-to-end number. One domain (Wyatt), one config (`C0-baseline`), dense retrieval
only. **Real baseline: hit_rate 0.80, MRR 0.80 (n=5).** A deliberate spike, not the harness
— marked as such in code (`chatbot/spike/`) and to be hardened, not shipped.

**Pipeline proven end-to-end.** crawl JSON → typed chunk → MiniLM embed → Qdrant → dense
retrieve → score, all C0-baseline values, running against a real Qdrant server. This
de-risks the full pipeline: every stage interface held, so Phase 2 is hardening known-good
seams rather than discovering them.

**Dense-only misses the summary-table question.** "What qualifications do you offer"
returns application-process prose, not the `/courses` table — even though that table is
chunked, stored as a `table` chunk, and present in the collection (course name and fee sit
together in one chunk; nothing is fragmented). The failure is retrieval ranking, not
chunking or recall-to-zero. This is first-party evidence motivating **RQ1** (hybrid
retrieval): the pipe-delimited table text embeds poorly against a natural-language question
about its contents. One clean data point, **n=1 — do not overclaim**; it is a hypothesis
with a witness, not a result.

**Test-set construction rules learned** (the harder-won output of the slice):
- **(a) Gold must list *every* page containing the answer**, not the first page thought of.
  A partial gold set understates recall and manufactures false misses.
- **(b) Never use a question whose answer keyword appears in site boilerplate.** "Lidcombe"
  appeared on all 15 pages (footer/contact chrome), so a Lidcombe question false-positived
  against every page. The keyword must be discriminating, not ambient.
- **(c) Never use a bare domain `/` as gold.** It substring-matches every URL — a wildcard
  that scores everything relevant. (Fixed in the matcher; see below and `docs/06` §1.)

**Source data conflicts internally — needs a stated scoring policy.** The corpus disagrees
with itself: the Diploma of Business fee is **$11,500** on the courses table but **$11,250**
on the course page; the Advanced Diploma duration is **"64 weeks"** vs **"1,080 hours"**.
A gold answer cannot be scored as simply right/wrong until the methodology states which
source wins (most-specific page? most-recent? both accepted?). Flagged for the evaluation
methodology — not yet decided.

**Two bugs found and fixed during the slice:**
- `qdrant-client` `search()` → `query_points()`: the installed client dropped `.search()`
  (version drift); migrated the spike store adapter, `(payload, score)` shape preserved.
- The `/` substring **wildcard** in relevance matching (rule (c) above): a bare-domain gold
  matched every URL. Fixed in the spike matcher with a regression test; the rule is recorded
  in `docs/06` §1 so the real `evaluation/metrics.py` inherits the exact-vs-substring split.

**LF-1 confirmed (control/text noise in chunks).** Cookie/analytics chrome appears in
retrieved chunk text, first-hand — reinforcing the deferred control/text-noise filtering
finding logged as LF-1 in `docs/08`. Not yet acted on; recorded here as live confirmation
rather than a new decision.