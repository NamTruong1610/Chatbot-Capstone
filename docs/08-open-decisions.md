# 08 — Open Decisions

Decisions that are **not mine to make**. Each blocks something. Take the ones marked
*supervisor* to Yining; decide the rest yourself and record the answer here.

Claude Code: if you hit an ambiguity not listed here, **add an entry and stop**. Do not
pick. A wrong assumption in research code produces a plausible number that is wrong,
which is the worst failure mode available (CLAUDE.md, Working style).

**Template:** Status · Question · Options · Recommendation · Blocks · Decider

---

## OD-3 — Generator model

**Status:** ☐ Open · **Decider:** supervisor · **Blocks:** P3-8, P5-7, the RQ3 design

Three positions in play: the proposal says Mistral-7B or Llama 3 8B; your prototype uses
`llama3.2` (3B); the hardware justification in the proposal is built explicitly around
7B-with-QLoRA at ≤16GB VRAM.

| | 3B | 7B/8B |
|---|---|---|
| Fits VRAM comfortably | Yes | Tight but the proposal says yes |
| Matches the proposal | No | Yes |
| Faster iteration | Yes | No |
| Fine-tuning headroom (RQ3) | Limited | Better |

**Recommendation: develop on 3B, run all reported experiments on 7B.** Keep the model in
config so this is a one-line change (FR-GEN-01). But decide *before* Phase 5 — a fine-tune
on the wrong base model is a week you cannot get back, and RQ3's whole framing is
"is this worth it for an SME on consumer hardware", which is a claim about the 7B case.

**Interim state.** `C0-baseline.yaml` carries `generation.model: llama3.2` so it validates
today. This is provisional, not a decision. Changing it before P5-8 is free — no
generation results exist until then, and no retrieval metric depends on the generator
(CLAUDE.md rule 8). Changing it after costs a re-run of every generation sweep.

---

## OD-4 — Is chunking strategy a fifth research question?

**Status:** ☐ Open · **Decider:** supervisor · **Blocks:** P5-4, and the thesis structure

The proposal treats chunking as a fixed implementation detail. Appendix A's one
documented failure was a chunking failure — a table split across boundaries, falling
outside top-k. Your supervisor also asked directly: *"what are the rules for chunking?"*

Configs `C5`–`C8` test this. The question is what to call it.

**Options**

- **(a) A fifth RQ.** Most honest. Requires amending the proposal.
- **(b) A sub-question of RQ1** — "retrieval quality" broadly construed. Cheapest.
- **(c) An implementation finding** reported in the discussion. Weakest, and buries the
  most interesting result.

**Recommendation: (b) now, (a) if the effect is large.** Run `C0` vs `C5` early, in
Phase 5. If the effect exceeds `C0` vs `C2`, you have a headline: *chunking strategy
dominates retrieval architecture at SME scale.* That is a more useful contribution than
confirming reranking helps, which Hu et al. (2026) already showed.

**Raise this with Yining before Phase 5**, since it changes what chapter 5 argues.

---

## OD-7 — Is embedding model an experimental arm?

**Status:** ☐ Open · **Decider:** you · **Blocks:** P5-2 compute budget

Gao et al. (2025) found no embedding model universally optimal across domains — directly
relevant to RQ4. But each embedding model needs its own ingest per domain, and the
compute budget is already 14+ ingests (`docs/07` §Compute budget).

**Recommendation: hold constant at `all-MiniLM-L6-v2`, note as a limitation.** Add it
back only if Phase 5 finishes early. The proposal names MiniLM specifically, and RQ4 has
enough to say without it.

---

## OD-8 — RAGAS judge model

**Status:** ☐ Open · **Decider:** you · **Blocks:** P5-9

LLM-as-judge scores are not comparable across judges. Pin one and never change it.

The sharper issue: if the judge is the same model family as the generator, they share
failure modes and faithfulness scores are inflated. Using a stronger, different model as
judge is methodologically cleaner but may mean a hosted API call per question.

**Recommendation: a different model family from the generator, pinned by version,
recorded in `run.json`.** Whatever you choose, state it in the methodology and list
shared-failure-mode risk as a threat to validity (`docs/06` §9).

---

## OD-9 — AI-synthesised test pairs

**Status:** ☐ Open · **Decider:** supervisor · **Blocks:** test set construction

The proposal names AI-synthesised Q&A pairs as the contingency if manual construction
slips. The risk: synthesised questions tend to be phrased in the corpus's own vocabulary,
which inflates retrieval scores relative to how real users ask.

**If used:**

- Flag every synthesised pair in the `notes` column
- Manually validate every one against the source
- **Report the synthesised proportion in the methodology**
- Ideally report retrieval metrics split by manual vs synthesised — if the gap is large,
  that is itself worth a paragraph

**Recommendation: manual-first, cap synthesised at 30%.** Agree the cap with Yining
before you need it, not in week 8 under time pressure.

---

## OD-10 — Does the workflow ablation deserve its own research question?

**Status:** ☐ Open · **Decider:** supervisor · **Blocks:** thesis structure

`C9-no-workflows` tests whether LLM-synthesised workflow documents outperform chunking
the same prose they were derived from. Nothing in your literature review covers this.
It is the direct test of your supervisor's central idea, and it is cheap — one extra
ingest per domain.

**This may be the most publishable single result in the project.** RQ1 confirms known
findings in a new context; RQ4 confirms Gao et al.; RQ3 adjudicates an existing debate.
The workflow ablation asks something nobody has asked.

**Recommendation: run it regardless of how it is framed.** Raise with Yining whether it
becomes a stated RQ or a substantial discussion finding — but the experiment happens
either way.

---

## Decided

*Move entries here with the date and rationale once settled. This is the audit trail of
design decisions for chapter 3.*

| ID | Decision | Date | Rationale |
|---|---|---|---|
| OD-1 | **Qdrant**, `Distance.COSINE`, in place of FAISS | 2026-07-24 | See below |
| OD-2 | **Direct SDK calls**; `langchain-text-splitters` only, inside the `recursive` chunker | 2026-07-24 | See below |
| OD-11 | Package is **`chatbot`**, not `app`. CLI is `python -m chatbot.config` | 2026-07-24 | Raised during P0 planning; `app` collides with the FastAPI `app = FastAPI()` convention and reads as a placeholder. `docs/02` and `docs/03` corrected. |
| OD-5 | Passive crawl needs no permission; interactive probing **enabled**, default target a **local mirror**; live probing allowed but deliberate | 2026-07-25 | See below |
| OD-6 | **Austral Manufacturing** (`austral-mfg`) + **Wyatt Education Group** (`wyatt-edu`) | 2026-07-25 | See below |

### OD-1 — Vector store: Qdrant with cosine distance

**Decision.** Qdrant replaces FAISS as the vector store. Distance metric is cosine.

**Rationale, in the order it should appear in the thesis.**

1. **RQ2 requires filtered retrieval.** Every query filters on `domain_id` (tenant
   isolation) and `access_level` (role scoping), across both the dense and sparse arms.
   Qdrant applies these as server-side payload filters *before* scoring, which is what
   makes `prefilter` a structural guarantee rather than a post-hoc check. Over FAISS the
   same behaviour has to be hand-built alongside the index, which is engineering effort
   that produces no findings.
2. **The switch costs nothing at the ranking level.** `all-MiniLM-L6-v2` emits normalised
   vectors. For normalised vectors, ranking by L2 distance and ranking by cosine
   similarity are equivalent — the nearest chunk by L2 is the highest-scoring chunk by
   cosine. So moving from FAISS/L2 to Qdrant/cosine cannot change which chunks are
   retrieved, and the Appendix A preliminary results remain comparable with the main
   study.

**Note the direction of that second point.** The equivalence is not the *reason* for
choosing Qdrant — it is what makes the choice free. Written the other way round
("we chose Qdrant because L2 and cosine are equivalent") it is a non-sequitur, since the
equivalence holds regardless of which store you pick. Metadata filtering is the reason;
the equivalence is the reassurance that the reason costs nothing.

**Follow-up actions**

- [ ] Amend the proposal methodology: the L2 derivation paragraph is now redundant as
      written. Replacement draft supplied separately — it keeps the normalisation
      argument, but repurposes it to justify the store change rather than to justify
      FAISS.
- [ ] Appendix A stays as written. It is an accurate record of a preliminary exercise
      that did use FAISS; note in chapter 3 that the main study moved to Qdrant and why.
- [x] `docs/02`, `docs/03`, `docs/04`, `docs/05`, `docs/07` updated.

### OD-2 — Orchestration: direct SDK calls

**Decision.** No orchestration framework. `langchain-text-splitters` is used, and only
inside `ingestion/chunking/recursive.py`.

**Rationale.** Orchestration frameworks abstract over precisely the parameters this study
must vary and report. RQ1 asks what reranking costs in latency; answering that needs the
call sites, not a chain that hides them. The framework would also sit between the config
system and the pipeline, which is the one seam that has to stay explicit for the
configuration matrix to mean anything.

**Follow-up**

- [ ] Amend the proposal methodology. Current text: *"implemented in Python using
      LangChain as the orchestration framework"*. Replace with: *"implemented in Python,
      using LangChain text splitters for the recursive chunking baseline"*. One sentence;
      do not leave the stronger claim standing.

### OD-5 — Crawl ethics: passive vs. interactive

**Decision.** The permission question was reframed after distinguishing two operations the
earlier draft had conflated.

- **Passive crawling** (P1-1, P1-4 — already built) fetches a page over HTTP and parses the
  HTML that was already sent. This is what a browser does and what any scraper does; it
  needs no permission beyond honouring `robots.txt`, which the crawler does. This covers
  the large majority of the data pipeline and is unblocked.
- **Interactive probing** (P1-5) clicks controls to reveal JS-injected content. Clicking
  *issues an action* against a server rather than reading a response, so it is treated with
  more care — but the care is scoped to P1-5 alone, not to the whole crawler.

**Resolution.**

1. Interactive probing is **enabled** as a capability; P1-5 gets built.
2. Default target is a **local mirror** of the chosen sites (`wget --mirror`, served on
   localhost). Against a mirror the `blocked_control_patterns` blocklist's leakiness is
   harmless — there is no live server to affect — and runs are more reproducible because
   the site cannot change mid-study. This aligns with FR-CRAWL-09 (persist raw corpus
   before processing).
3. Live-site probing is **allowed but deliberate**: `request_delay` enforced, blocklist on,
   and the `controls_blocked` manifest reviewed after the first run against each site to
   confirm nothing transactional got through.
4. `interaction_probing` therefore defaults to **false for live crawls** and is turned on
   for mirror crawls.

**Why not "written permission from each business", as first drafted.** Passive scraping of
published pages does not require it, and interactive probing against a local mirror does
not touch the business's infrastructure at all. Permission-seeking was solving a problem
the mirror approach dissolves. The residual live-probing path is governed by rate-limiting
and the blocklist, not by consent.

**Open sub-question, deferred to site inspection, not blocking.** Whether the two chosen
sites have workflow steps that only render after a *server round-trip* (a button that
fetches live data, a step-2 form generated server-side). A static mirror cannot capture
those. If a target workflow has that shape, that specific workflow may need live probing;
most affordance structure (forms, buttons, their labels and targets) is in the mirrored
HTML/JS and does not. Check once the sites are mirrored.

**Rendering wait strategy (`render_wait`) — live-crawl observation.** Observed 2026-07-25
on live crawls: networkidle times out and drops the page on institution-scale sites
(uts.edu.au); on Wyatt it matched domcontentloaded exactly. Baseline set to
domcontentloaded — deterministic, cannot hang, no content cost on the study sites.
(FR-CRAWL-02; baseline `config_hash` 364b8852… → 211286c8….)

### OD-6 — The two SME domains

**Decision.** **Austral Manufacturing** (`austral-mfg`, https://australmanufacturing.com.au/)
and **Wyatt Education Group** (`wyatt-edu`, https://wyatt.nsw.edu.au/).

**Both are genuine SMEs** — a Penrith metal-fabrication shop and a Bankstown registered
training organisation — which keeps the study aligned with its SME framing. Earlier
candidates (IMDb, Reddit) were rejected as large non-SME platforms that also prohibit
scraping and lack extractable workflows. Brand Furniture was rejected as a five-page
Squarespace portfolio with no workflow and thin, image-heavy text.

**They satisfy the selection criteria:**

| Criterion | Austral | Wyatt |
|---|---|---|
| Genuine SME | ✓ metal fabrication | ✓ vocational RTO |
| Real multi-step workflow | ✓ Free Quote flow | ✓ Enrolment, Apply, RPL assessment |
| Tabular content | ✓ (check Capabilities/coating spec tables) | ✓ course catalogue: code, CRICOS, duration, location, mode |
| `qa` content | ✓ FAQ page | ✓ FAQ page |
| **Different content shape (RQ4)** | brochure + single conversion form | structured catalogue + application pipeline + policy/compliance pages |
| Crawler backend exercised | WordPress/Elementor, mostly server-rendered | GTM + dynamic widgets, exercises Playwright (P1-2) |

**The content-shape contrast is the RQ4 justification.** Two manufacturers would have been
near-neighbours; a fabrication shop and a vocational college have genuinely different
information architectures — one a brochure with a quote form, the other an enumerable
course catalogue with a multi-step enrolment pipeline. RQ4 tests generalisation across
content structure, and this pair provides it. As an incidental benefit, Austral is
mostly static (static crawler) while Wyatt is more dynamic (Playwright), so the two
domains exercise both crawler backends.

**Note the private tier is synthesized** (see the access-control resolution): RQ2 does not
need the sites to have a real public/private division, because access control tests
who-can-reach-what, not the content itself. Synthesizing the private tier gives exact
ground-truth labels and removes the ingest-mislabelling confound. Criterion 5 from the
original list ("plausible public/private division") is therefore dropped.

**Write-up caution.** Wyatt is education-sector and so is the UTS *reference* corpus from
Appendix A. The two study domains are Austral and Wyatt; UTS is preliminary scaffolding,
not a third domain. Keep the RQ4 generalisation claim explicitly Austral↔Wyatt so a marker
does not read it as "two education sites".

**Follow-up actions**

- [ ] Confirm at least one real `<table>` (or table-shaped content) on an Austral service
      page before first ingest — the Capabilities and Powder Coating pages are the likely
      homes. If none exists, `C7-table-split` loses its Austral signal and leans entirely
      on Wyatt's course tables.
- [ ] Mirror both sites locally before interaction probing (OD-5).
- [ ] Synthesize the private tier for each domain, tagged `access_rule: explicit`.


---

## Logged findings

Deferred engineering findings from live crawls — not decisions, not fixed now; tracked so
the owning phase picks them up.

### LF-1 — Control extraction captures page chrome (workflow-extraction phase)

Observed on the Wyatt live crawl (2026-07-25): control extraction currently captures page
chrome — cookie-consent banners ("Accept cookies", "Decline"), modal close buttons ("✕"),
and empty-label controls — as controls. This inflates the control count and would pollute
inferred workflows with non-steps.

**Deferred fix:** a filtering pass at workflow-extraction time (FR-WF) that excludes
consent/modal/nav chrome and empty-label controls before controls become workflow steps.
This is not a crawler change — the crawler faithfully records what is on the page; the
judgement about what counts as a *workflow step* belongs to workflow extraction. Logged,
not fixed now.

### LF-2 — `typed` implements three of four rules; workflow-atomic deferred (FR-WF phase)

The `typed` chunker (Phase 2) implements the **table**, **qa**, and **prose** rules of
FR-CHUNK-02. The fourth rule — **workflow** kept atomic — is **not** implemented: it
consumes synthesised `Workflow` objects, and workflow extraction (FR-WF) is a later phase
with no `Workflow` data model built yet. Inventing that model inside a chunking phase would
pre-empt FR-WF's design.

Recorded so "typed chunking" is never silently read as all four rules. **Owning phase:**
FR-WF. When it lands it adds the `Workflow` type, `chunk_workflow` to the `Chunker` protocol
(docs/04 §3), and the atomic rule + tests. No results measured with `typed` before then
exercise workflow chunks, so nothing needs re-running on account of the gap.

### LF-3 — `typed` prose segmentation assumes headings appear as lines in page text

`typed` builds heading-bounded sections (and pairs FAQ Q/A) by locating each heading's text
as a line within the page's flat `text` blob — because `CrawledPage` carries a flat `text`
plus a flat `headings` list with no explicit mapping between them. The Phase 2 fixtures are
built to satisfy that shape, and it is unverified against real crawler output.

**Verify before trusting `typed` on live data:** on the next real-pipeline run, check that a
real Wyatt page's `text` actually contains its heading strings as standalone lines (and that
body prose is attributed to the right heading). If real `text` inlines headings differently
(e.g. headings absent from `text`, or run together with body), the segmenter under-sections
and breadcrumbs/QA pairing degrade. Flagged for the next real-pipeline run, not fixed now.