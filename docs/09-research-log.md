# 09 — Research Log

Dated, append-only record of experiments actually run and what they taught. Distinct from
`docs/08-open-decisions.md` (pending decisions) and the results files (`results/`, machine
output): this is the human narrative a marker and future-you read to understand *why* the
pipeline is shaped the way it is. Newest entry first. Never edit a past entry — correct it
with a new one.

---

## 2026-08-14 — RQ4: the pipeline generalises; prose (Austral) beats tables (Wyatt) at both retrieval and generation (MEASURED)

The cross-domain generalisation study — the **same** pipeline (C0-baseline, no code or config
change; `domain_id` is a free string) run against a **second domain**: Austral, an 8-page,
prose-heavy manufacturing site with **zero tables**, on a 21-question test set. Compared against
Wyatt (table-heavy training/education site). RQ4 needed nothing built — it fell out of the
domain-agnostic machinery, exactly as docs/03 §3 predicted.

**Result: the pipeline generalises, and prose is *easier* than tables on both axes.**

| Metric | Austral (prose) | Wyatt (tables) |
|---|---|---|
| Retrieval page-hit | **1.000** | 0.833 |
| Retrieval answer-hit | **0.889** | 0.706 |
| Generation containment | **0.882** | 0.529 |
| Refusal accuracy | ~1.0 (corrected) | 1.0 (corrected) |

- **Prose retrieves cleaner.** Austral's answer-hit 0.889 > Wyatt's 0.706. Prose passages embed
  as focused single-topic vectors; there is no **force-2 blur** (the dense mean-pooling dilution
  that buried Wyatt's multi-record table chunks, docs/09 2026-07-26). Structure, not domain, drove
  Wyatt's retrieval difficulty.
- **Prose generates cleaner.** Austral containment 0.882 vs Wyatt 0.529, with clean answers — no
  raw-chunk-dumps, no invented facts, no citation leakage. This **confirms table structure drove
  much of Wyatt's answer messiness** (LF-4): pipe-delimited table rows were what the model dumped
  raw; prose gives it well-formed text to paraphrase.

**The clean cross-domain contrast — two structure-dependent failure modes:**
- **Wyatt / tables:** force-2 retrieval blur + raw-table-dump generation + table-orphaning
  (a record split across chunks). All table-specific; none appear on prose.
- **Austral / prose:** **one retrieval-recall miss** — case 4 (design software). SolidWorks and
  AutoCAD *are* on the site, but the answer unit did not rank in the top-5 for that phrasing
  (retrieval eval answer_hit=0), so the generator — correctly — refused rather than invent. That
  is a **retrieval-recall** miss on a phrasing gap, not a generation failure and not
  table-orphaning. Generation grounded correctly on content it never received.

So the two domains fail in *different, structure-linked* ways: Wyatt's tables orphan/blur;
Austral's prose occasionally misses on recall for an unusual phrasing. Neither is a general
pipeline defect — which is the RQ4 point: the pipeline works across content structures, and the
residual failure modes are properties of the *content*, not the machinery.

**Methodology repeated, and it paid off again.** Reading the answers caught a mislabel, same as
Wyatt: **case 20 (3D printing)** was flagged HALLUCINATION but is a *correct nuanced answer* — the
chatbot said 3D printing is not offered while accurately noting Austral does 2D/3D **design** (true,
on-site). Reclassify to correct-handling (as Wyatt case 19); real refusal-accuracy is ~1.0, not
0.667. This is the third time the containment/refusal metric under-measured a correct nuanced
answer and human-reading recovered it — the pattern is now a documented, load-bearing part of the
evaluation method, not an incident. (Local fix: set case 20's `question_type` to `factual_lookup`
in `austral_rq4.csv`, mirroring the Wyatt 18/19 correction.)

**Minor:** case 13 mangled an address — dropped the unit prefix ("Unit 6/14 Peachtree"), kept
"Rd, Penrith". An answer-quality glitch (prose extraction of a multi-part address), noted; not a
retrieval or isolation issue.

**Contribution.** RQ4's answer: **the pipeline generalises across businesses and content
structures.** Prose (Austral) retrieves and generates *better* than tables (Wyatt); the
table-handling challenges surfaced across RQ1/Phase-5 (force-2 blur, raw-chunk dump) are
**table-specific and absent on prose**, and the one prose failure is a bounded retrieval-recall
miss. A clean structure-driven contrast across two real SME domains, same machinery, results
grouped by `domain_id` (FR-EVAL-08).

---

## 2026-08-02 — RQ2: prefilter+enforce achieves ZERO private leaks end-to-end (MEASURED)

The access-control isolation run — `acl-eval` over a 12-case RQ2 set (10 private-lookup + 2
public-control) under **both** roles, C0-baseline (`strategy: prefilter`), against a real index
that includes 5 synthesised private staff docs ingested with `--private-corpus`. The private
facts carry **unique tracer strings** (`WYT-AG-0447`, `Diana Reyes`, `$1,800`, …) so any leak is
unambiguous.

**Result: ISOLATION PASS.** `customer_leaked_chunks = 0` and `tracer_leaks_in_customer_answer = 0`
across all 10 private questions (raw counts — docs/06 §4). Every customer **abstains** on private
questions; the private facts (incl. `WYT-AG-0447` / `Diana Reyes`) reach **staff only**. Public
control **2/2** — both roles still answer public content, so isolation is not achieved by breaking
the chatbot. `staff_access 9/10` — the one miss (case 6, compliance-officer question) is a staff
**retrieval/paraphrase** miss, not an isolation failure (staff were *permitted* the chunk; it just
wasn't retrieved/stated). Isolation and access are different axes and the eval keeps them separate.

**The contribution: a double-guard, both barriers verified live.**
- **Barrier 1 — prefilter.** The customer's role resolves to `{public}`, passed as Qdrant's
  server-side `access_level` filter, so private chunks are **never scored** (FR-ACL-03).
- **Barrier 2 — enforce backstop.** Runs on every query even under prefilter: a private chunk
  reaching it from *any* arm is dropped, counted (raw), and logged (FR-ACL-07). Isolation does not
  depend on a single arm filtering correctly. Fail-closed on an unknown role (rule 4); `none` mode
  harness-gated (FR-ACL-05).

**Why the check is on the customer's ANSWER, not just retrieval.** The security claim is that a
customer never *sees* the secret. So the leak test is the tracer string in the customer's final
generated answer (plus the raw enforce chunk count) — end-to-end, not retrieval-only.

**A sharp illustration — customer-answered ≠ customer-leaked (case 0).** Asked a private question,
the customer produced a *wrong* answer ("$1,500") — but the real private figure (`$1,800`) did
**not** appear. The customer hallucinated a plausible number rather than leaking the secret, and
the tracer check correctly scores this as **no leak**: it distinguishes "the customer said
something" from "the customer revealed the protected fact." A page-level or did-the-customer-answer
metric would miss this distinction; the tracer-in-answer check is what makes the isolation claim
precise.

**Measurement fix during the run.** The per-case CLI label wrongly flagged the public-control rows
as `LEAK!` — on a public row the "tracer" *is* the public fact and the customer is supposed to
state it. Fixed with a tested `is_leak` helper (leak only on a private-row tracer or a leaked
chunk); the aggregate was already correct (`tracer_leaks` counts private rows only), so no number
changed.

**Contribution.** RQ2's answer on the isolation question: a **prefilter + enforce double-guard**
delivers **zero private leaks end-to-end**, verified with unique tracer strings across public
(customer) and private (staff) users; staff retain access and public content is unaffected. The
deliverable — labels → per-document override + `--private-corpus` ingest → the two-barrier filter →
a two-role isolation eval that counts leaks raw and checks the customer's answer — is done. (RQ2's
`postfilter`/`none` *comparison* arms, C11/C12, are a separate later study; this phase built and
proved enforcement.)

---

## 2026-08-02 — Prompt polish cleaned the answers (0.294→0.529); two retrieval-precision limits remain (MEASURED)

A `strict_grounded`-only pass (LF-4) — no code, metric, or test-set change — fixed the answer
*quality* defects the generation read surfaced, and moved the containment proxy without touching
grounding/refusal:

- **Cleaner answers, measurably.** Citation-marker leakage gone (clean prose throughout), raw
  pipe-delimited chunk-dump gone (case 10), bare-citation non-answers fixed (cases 15/16 now state
  the phone number / the year in words). **grounding-correctness 0.294 → 0.529** — the rise is
  because answers now *state the fact in words* (so the containment ruler can see it), not because
  retrieval changed. Refusal accuracy still **1.0**, **zero hallucinations**, and the case-19
  partial-information hedge survived. Behaviour held; prose improved.
- The jump also re-confirms the proxy's nature: it rewards the fact appearing in the text, which is
  a genuine quality gain here — but it is still a floor (see the limits below, which it cannot
  catch).

**Known limitations — retrieval-precision, NOT prose (out of scope for a prompt pass).** Two
answers are wrong because the model faithfully grounded in a **wrong-but-present** retrieved chunk:

- **Case 0 (qualifications):** the answer still lists generic AQF degree levels
  (Bachelor's / Advanced Diploma / …) Wyatt does not offer. A retrieved chunk contains a generic
  **AQF framework**, and the model repeats it instead of naming Wyatt's four actual courses. The
  prompt now forbids outside knowledge, so this is not invention — it is grounding in the wrong
  chunk. Fix is retrieval precision (don't surface / don't rank the AQF-boilerplate chunk), not the
  prompt.
- **Case 17 (cost difference):** asked about the **Business** diploma, the answer used the
  **Building & Construction** diploma's fee — the model grabbed the wrong course's figure from
  present context. Again retrieval precision, not phrasing.

Both are the same failure mode — **faithful grounding in the wrong retrieved context** — which is
distinct from the (now-fixed) prose quality and from hallucination (the model is *not* making
things up; it is repeating the wrong real chunk). It motivates retrieval-precision work
(reranking/chunk-scoping) and is tracked as LF-5; not fixed in this pass. The chatbot's answers are
otherwise clean and demo-ready.

---

## 2026-08-01 — Generation on Wyatt: grounds + refuses correctly; the metric under-measures, and reading the answers caught the mislabels (MEASURED)

First end-to-end chatbot run — `chat-eval` over `wyatt_rq1.csv` through the **same**
`build_chat_pipeline` the API serves (C0-baseline, dense retrieval, llama3.2, `strict_grounded`,
temperature 0.0). The headline is not a number; it is that the automated number was **wrong until
a human read the answers against the source**.

**Behaviour is correct.** Zero hallucinations. The one genuine out-of-scope question (ATAR — not
applicable to VET, absent from the site) is **refused** with the exact abstention phrase;
**refusal accuracy = 1.0**. The two hard cases are handled well:

- **Source conflict resolved, not parroted.** The Diploma of Business fee reads $11,500 on the
  courses table but $11,250 on the course page. The chatbot did not pick one blindly — it grounded
  the reconciliation: **$11,500 = $11,250 tuition + $250 fee**. That is the RAG pipeline doing
  exactly what it should with self-inconsistent source data.
- **Partial information handled honestly.** "Is there a payment plan?" — the exact term is not on
  the site, but related financial terms are. The chatbot **surfaced the deposit and administration
  fee and declined to invent a payment plan** — the correct behaviour for a partial-information
  query (case 19, now classified `factual_lookup`; see the ground-truth correction below).

**The containment proxy is a floor, not the score. grounding-correctness (fact contained) =
0.294** — and that number *under-measures* quality, badly. Focused, correct answers routinely omit
the literal `answer_terms` the question already established (e.g. answering "52 weeks" without
repeating "Diploma of Business") and score `fact=miss` while being right. The proxy checks fact
**containment, not quality** (docs/06 §5.1, OD-14); it is worth reporting only as a floor, and the
**printed answers are the real evidence** — which is why `chat-eval` prints every answer.

**Methodological finding (the actual contribution).** The first automated run reported refusal
accuracy 0.333 and three "hallucinations." Reading the model's answers against the crawl showed
**all three were test-set mislabels, not model failures**: a bursary (partial scholarship) *is* on
the site (case 18), and the case-19 financial terms *are* on `/enrolment`; only ATAR was truly
out-of-scope. Correcting the ground truth moved refusal accuracy 0.333 → **1.0** with no change to
the model. The metric alone would have recorded a hallucinating chatbot; the human read recovered
the truth. This is the generation analogue of the RQ1 page-level-blindness lesson: **an automated
grounding number is only trustworthy once someone has read the outputs against the source.** Human
reading is not optional QA — it is what keeps the number honest.

**Ground-truth correction (2026-08-01).** cases 18/19 reclassified out_of_scope→`factual_lookup`;
`answer_terms` left empty (behaviour-scored answer-vs-refuse; quality read by human), so RQ1's
answer-span set stays n=17 and its headline is unaffected (see the RQ1 note below). "bursary"
appears on 9 pages — ambient, so it is not used as a containment term (the discriminating-keyword
rule from the thin-slice findings).

**Scope.** Answer *quality* issues (invented specifics, raw-chunk echo, citation-fragment leakage,
citation-only non-answers) are real but separate from the grounding/refusal behaviour measured
here; they are prompt-tunable and logged as LF-4 for a prompt-polish pass, not a pipeline defect.
The deliverable — a working, config-driven chatbot endpoint plus a generation harness that scores
refusal by cause and prints answers for human grounding-review — is done.

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