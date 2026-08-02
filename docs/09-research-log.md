# 09 — Research Log

Dated, append-only record of experiments actually run and what they taught. Distinct from
`docs/08-open-decisions.md` (pending decisions) and the results files (`results/`, machine
output): this is the human narrative a marker and future-you read to understand *why* the
pipeline is shaped the way it is. Newest entry first. Never edit a past entry — correct it
with a new one.

---

## 2026-08-01 — RQ1 on Wyatt: hybrid alone regresses, rerank nets +1/17 at ~2.5× latency (MEASURED)

The first real RQ1 comparison — dense (C0) vs hybrid (C1) vs hybrid+rerank (C2), same
ingested index (shared `index_key`, no re-ingest), scored on the 21-case `wyatt_rq1.csv`
(17 answer-scored; 3 out_of_scope + 1 null unit). **Answer-span is the finding; page-level did
not separate the arms** (every arm returns a chunk from the gold page — the same blindness the
chunking study flagged), so the numbers below are `answer_hit_at_k`, k=5.

| config | mode | answer_hit_rate | per-query latency |
|---|---|---|---|
| C0-baseline | dense | **0.706** (12/17) | ~54 ms |
| C1-hybrid | dense + BM25 (RRF) | **0.588** (10/17) | ~43 ms |
| C2-hybrid-rerank | hybrid + cross-encoder | **0.765** (13/17) | ~122 ms (median) |

The aggregate hides the real story; at n=17 the per-case movement is the finding:

- **Hybrid alone REGRESSES.** C1 broke exactly two cases that dense got — **case 2** (Advanced
  Diploma duration) and **case 15** (phone number), both 1→0 — and gained none. That pair *is*
  the entire 0.706→0.588 drop. BM25's exact-token matching pulled lexically-similar but
  answer-empty chunks into the fused top-5, displacing the dense hits. On a ~530-chunk SME
  corpus the sparse arm adds more noise than signal.
- **Rerank recovers the damage and nets one genuinely new question.** C2 restored cases 2 and
  15 (the cross-encoder re-scored the noise back down) **and** additionally fixed **case 1**
  (Diploma of Business duration), which *both* dense and hybrid missed. So relative to C0 the
  net gain is **+1/17 — a single question (case 1)** — and most of rerank's visible work is
  undoing hybrid's own regression, not beating dense.
- **The force-2 prediction is FALSIFIED.** The chunking entry below predicted BM25 would rescue
  **case 8** (`CPCCBC4001`) where dense's mean-pooled vector buries the unit in a multi-record
  chunk. On the real corpus **case 8 HIT under all three arms — dense already retrieved it** —
  so the predicted table-rescue never fired. The force-2 mechanism is real in the constructed
  fixture (`test_hybrid`) but did not manifest on Wyatt: the answer-bearing chunk was not
  actually orphaned at retrieval time. Tested and disconfirmed; recorded as such, not buried.

**Latency.** C2's per-query cost is ~122 ms median (mean 145 ms after the warm-up fix, commit
`0a82dd5`, moved the one-time cross-encoder load out of the timed loop; the pre-fix mean of
1669 ms was a case-0 cold-start artifact, not query cost). So rerank is **~2.5× dense** (54→122
ms), not 30×. All arms are well under 150 ms — latency is not the deciding factor here; accuracy
is, and the accuracy gain is one question.

**Build decision — both defensible, neither compelling.** For a live SME chatbot: **rerank** is
the best-accuracy arm and still sub-150 ms, or **dense** is simpler and cheaper at one question
worse with no moving parts. **Hybrid-without-rerank is dominated — do not ship it**; on this
corpus it strictly regresses dense. The pragmatic default is **dense**: the +1/17 rerank edge
does not justify a cross-encoder dependency and 2.5× latency for most SME deployments.

**Status: directional, NOT statistically significant.** n=17 answer-scored on one domain; a
one- or two-question swing moves every aggregate. This is a witnessed pattern, not a result to
generalise — RQ4 (does it hold across businesses?) is where significance would have to come
from. Caveat: C0 here is "C0 minus workflows" (FR-WF unbuilt, LF-2), so absolute numbers are a
floor; the *relative* comparison is unaffected (all three arms share the same index).

> **Later correction (2026-08-01):** cases 18/19 were reclassified out_of_scope→factual_lookup
> (see the generation entry above). `answer_terms` were left empty on both, so the RQ1
> **answer-span** set stays n=17 and the headline numbers above are unchanged; only the RQ1
> **page-level** aggregate predates the correction (those two cases now carry gold pages). RQ1
> was **not** re-run — page-level did not separate the arms, so the correction does not change
> what RQ1 concluded.

**Apparatus verified before trusting the numbers.** Dispatch was confirmed to reach the right
retriever per config (C0→dense, C1→hybrid, C2→hybrid_rerank), `index_key` is identical across
the three (so C1/C2 genuinely reuse C0's index), and the BM25 arm demonstrably contributed —
C1 ≠ C0 (it changed results, for the worse) is itself the proof the sparse arm ran. An earlier
sweep re-ingested per config; harmless (same `index_key`, deterministic point ids) but the
reason: `ingest` has no skip-on-existing guard — ingest C0 once, only *run* C1/C2. Logged as a
usability gap, not a correctness one.

**Contribution.** RQ1's answer on SME-scale data: **hybrid retrieval does not help and can
hurt; reranking recovers hybrid's damage and adds marginal value over dense, at a latency cost
that is real but small.** The force-2 hypothesis that motivated the hybrid arm held in
principle but did not fire on this corpus. The deliverable — three switchable, registry-selected
retrievers measured on the same index with a metric that sees intra-page answer placement — is
sound regardless of which arm "won."

---

## 2026-07-26 — C0 vs C5 on Wyatt: chunking is near-neutral, two opposing forces (MEASURED)

The measured result from the committed harness — dense retrieval, `top_k=5`, answer-span
scored on the live Wyatt index: **answer_hit_rate C0 (typed) = 0.25, C5 (fixed) = 0.75
(n=4 answer-scored cases).** Naive char-fixed slightly *beats* typed on this corpus — the
opposite of Appendix A's prediction. Reading the actual ranks/scores per chunk, two opposing
forces explain it, and neither dominates:

- **Force 1 — chunk integrity (favours typed; Appendix A's concern).** Fragmenting a record
  across chunks can orphan the answer so no single chunk carries the full unit. **On Wyatt
  this barely fires.** Compact tables (the 4-row courses table) fit inside one ~400-char
  window, so nothing orphans. And `typed` does **not** emit a giant whole-table chunk either:
  `header_repeat` packs rows only until `size` (400), so *both* configs produce ~400-char
  chunks. The force-1 scan found **no** Wyatt question where C5 orphans the answer in the
  index *and* a C0 chunk carrying it ranks top-5. Force 1 does not survive to retrieval here.
- **Force 2 — chunk focus (favours fixed).** For a *specific-unit* question ("what does
  CPCCBC4001 cover?"), C0's row-group chunk mixes several units' text, so its mean-pooled
  MiniLM vector is a muddier match than a C5 window dominated by that unit's tokens.
  **Measured: C0's full-unit chunk ranked below C5's focused fragment** for the query — a real
  dense-retrieval effect. It is **not** a matching bug: the matcher provably requires all
  components in one chunk (a severed pair scores MISS), so C5's live hits come from single
  windows that genuinely contain the whole unit on the real page.

**Finding.** On SME-scale corpora like Wyatt, **chunking strategy is near-neutral, slightly
favouring `fixed`.** The contribution is the pair of forces — **chunk-integrity vs
chunk-focus** — trading off along **table-size × question-specificity**: integrity only
matters for records long enough to orphan (rare at 400 chars), while focus penalises any
chunk that averages unrelated records for a specific query. Page-level metrics are blind to
both (both configs return a chunk from the gold page); answer-span (docs/06 §1.1) is what made
the tradeoff visible.

**Supersession.** This committed-code, retrieval-scored result **supersedes the earlier
"C0 HIT / C5 MISS" observation**, which was a *chunk-level* artifact on a fixture sized to
sever. Under live retrieval the real page did not orphan and force 2 pushed the result the
other way. The chunk-level `test_answer_span_effect` stays valid as a unit test of the
matcher's one-chunk rule on a constructed page — it is **not** a claim about the Wyatt corpus.

**Bridge to RQ1.** Force 2 (dense embedding dilution on multi-record chunks) is exactly what
**hybrid retrieval (RQ1)** should fix: BM25 matches `CPCCBC4001` lexically regardless of
mean-pooling geometry, so it should rescue the whole-record chunk that dense retrieval buries.
The chunking sub-question is answered and hands off to the primary RQ.

The retrieval spine, the answer-span metric, and the fingerprint-guarded harness are correct
and valuable regardless of which config "won" — the apparatus is the deliverable; the finding
is simply different from the draft. Chunking comparison **closed**.

---

## 2026-07-26 — The naive-chunking penalty is table-size-dependent (and answer-span measures it)

> **Superseded by the measured entry above.** The "C0 hit / C5 miss" below was a *chunk-level*
> result on a constructed fixture; it did **not** reproduce under live retrieval (force 2 —
> see above). Kept for the reasoning path (why we built answer-span); read the corrected entry
> for the actual C0-vs-C5 result.

With `fixed` corrected to char-based (OD-13), the C0-vs-C5 picture *at the chunk level*
resolved into what looked like a precise finding on a constructed severing fixture:

- **Compact table (courses, 4 rows): survives char-fixed.** The whole flattened table fits
  inside one ~400-char window, so a fee stays with its course name under both configs. The
  two fee questions **tie** — C0 and C5 both retrieve the answer whole. *(This part held.)*
- **Long table (fixture): the code and its operative phrase split across char-windows**, so
  no single C5 chunk carried the whole unit while a C0 chunk did. **On the real Wyatt page
  this did NOT reproduce** — the real record did not exceed one window, and force 2 dominated.

**The (revised) contribution:** the naive-chunking penalty is not universal — chunk *integrity*
only matters for records long enough to orphan, which Wyatt's tables at 400 chars do not
reliably reach; and it is opposed by chunk *focus* (force 2). See the corrected entry above.

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