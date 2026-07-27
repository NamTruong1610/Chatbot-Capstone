# 09 — Research Log

Dated, append-only record of experiments actually run and what they taught. Distinct from
`docs/08-open-decisions.md` (pending decisions) and the results files (`results/`, machine
output): this is the human narrative a marker and future-you read to understand *why* the
pipeline is shaped the way it is. Newest entry first. Never edit a past entry — correct it
with a new one.

---

## 2026-07-26 — First real C0-vs-C5 comparison on Wyatt (answer-span validated)

The first real, ruler-validated retrieval comparison, confirmed on real Wyatt chunks. Three
findings, reported together because they only make sense together:

- **(a) Answer-span, long table — C0 HIT / C5 MISS.** *"What does unit CPCCBC4001 cover?"*
  (source: the Diploma of Building & Construction unit list, an 8-row table). Typed (C0)
  keeps the unit's row whole, so one chunk carries the code **and** its operative description
  ("National Construction Code") → answer-relevant. Char-fixed (C5) hard-cuts the flattened
  page text, landing the code and that phrase in **different** windows → no chunk carries the
  usable unit → miss.
- **(b) Answer-span, compact table — C0/C5 TIE (both HIT).** The fee questions (Diploma of
  Business international fee; Certificate III tiling fee) live in the compact 4-row courses
  table, which fits inside one char-window, so the answer survives char-fixed intact — both
  configs hit.
- **(c) Page-level — tied, blind.** Both configs return a chunk from the gold page for every
  case, so page-level hit_rate is identical C0=C5 and cannot see (a). The docs/06 §1
  limitation, live.

**Finding.** Naive fixed-size chunking orphans records from **long** tables but not **compact**
ones — the penalty is **table-size- (span-distance-) dependent** — and it is **invisible to
page-level metrics, visible only to answer-span** (docs/06 §1.1). The honest, precise
contribution is not "chunking dominates retrieval" but "naive chunking has a specific,
measurable failure on long structured records that the standard page-level ruler misses."

**Supersession.** This replaces the earlier C0≈C5 null, which was a **mis-reproduction**: the
retired line-based `fixed` never fragmented the crawler's whitespace-normalised single-line
text, so it could not orphan anything. Char-based `fixed` (OD-13) is the faithful naive
baseline; the effect above is on that corrected arm.

**Provenance.** Answer-span components authored **blind** (question + source page, docs/06
§1.1): `CPCCBC4001` (the unit the question names) and `National Construction Code` (the
operative substance of its description) — not derived from any config's output. Chunk-level
HIT/MISS is proven deterministically in `test_answer_span_effect`; the scored top-k readout
is the harness `run` command (needs the live corpus + Qdrant + model).

---

## 2026-07-26 — The naive-chunking penalty is table-size-dependent (and answer-span measures it)

With `fixed` corrected to char-based (OD-13), the C0-vs-C5 picture resolved into a precise,
reportable finding — confirmed on real chunks from the Wyatt corpus:

- **Compact table (courses, 4 rows): survives char-fixed.** The whole flattened table fits
  inside one ~400-char window, so a fee stays with its course name under both configs. The
  two fee questions **tie** — C0 and C5 both retrieve the answer whole.
- **Long table (Building & Construction unit list, 8 rows): orphaned by char-fixed.** The
  operative phrase of unit `CPCCBC4001` ("National Construction Code") lands in a *different*
  char-window from its code, so no single C5 chunk answers "what does CPCCBC4001 cover?".
  Typed keeps the table row whole, so C0 answers it. C0 **hit**, C5 **miss**.

**The contribution:** the naive-chunking penalty is not universal — it is **table-size-
(more precisely, span-distance-) dependent**. Char-fixed only orphans an answer whose
components sit more than ~one window apart in the flattened text (a long table, or a value
tied to a far-away column header); adjacent answer-units (a fee in its row, a short
code+title) survive at any position. This is a sharper and more honest claim than "chunking
dominates retrieval."

**Measuring it required a new ruler.** Page-level relevance is blind to this (both configs
return a chunk from the right page). So we added **answer-span relevance** (docs/06 §1.1): a
chunk counts only if the answer's *usable unit* co-occurs in it. The `CPCCBC4001` case is the
positive control (C0 answer-hit, C5 answer-miss); the fee cases are the negative controls
(both hit). Components are authored blind — from the question and source page, never from what
a config retrieved — or the metric would manufacture its own result. Answer-span is reported
**alongside** page-level, never replacing it.

---

## 2026-07-26 — Why C0 ≈ C5, and the C5 redefinition (pre-harness diagnosis)

Building toward the first real C0-vs-C5 comparison, C0 and C5 looked identical and we stopped
to find out why **before** building the scoring harness on top. The chain of findings:

- **Page-level relevance is blind to intra-page chunking damage.** Every chunk from a page
  carries that page's `source_url`, and page-level match keys on `source_url` alone — so a
  config that keeps a table whole and one that shreds it both "hit" the gold page. Confirmed
  structurally; it is exactly the limitation docs/06 §1 already flags.
- **The chunker keeps table rows atomic.** `_layout` renders each table row as one
  pipe-joined line, and the (then) line-based `fixed` split on line *count*, so a row was
  never cut — "Diploma of Business" and "$11,500" stayed together under both configs.
- **The real crawler flattens the whole body — including the table — into a single-line
  `page.text`** (`extract_main_text = _norm(body.get_text(" "))`). So even the structured
  table's content reappears, flattened, in the prose text; any chunk carrying `page.text`
  holds the full record. The earlier fixture misled us because its `text` omitted the table.
- **Root cause: line-based `fixed` is degenerate on normalised text.** With `page.text` a
  single line, "N lines" cannot fragment prose — one chunk for the whole page. That is not
  the naive fixed-size baseline the literature and Appendix A describe.

**Decision (OD-13):** redefine `C5 fixed` as **character-based** (hard `size`-char windows,
no boundary respect), retire line-based `fixed`. This is a correctness fix to the baseline,
not effect-hunting — **a second null under the corrected baseline is a valid finding.** The
answer-span metric (a chunk is answer-relevant only if the answer's *usable unit* co-occurs
in one chunk — e.g. course name + column header + figure) is designed and reviewed but **not
built**: we do not build a ruler until the real chunks show there is an effect to measure.
Next: re-run the real chunk dump under char-based C5 and report whatever it shows, including
another null.


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