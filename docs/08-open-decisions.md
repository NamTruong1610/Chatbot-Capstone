# 08 — Open Decisions

Decisions that are **not mine to make**. Each blocks something. Take the ones marked
*supervisor* to Yining; decide the rest yourself and record the answer here.

Claude Code: if you hit an ambiguity not listed here, **add an entry and stop**. Do not
pick. A wrong assumption in research code produces a plausible number that is wrong,
which is the worst failure mode available (CLAUDE.md, Working style).

**Template:** Status · Question · Options · Recommendation · Blocks · Decider

---

## OD-2 — LangChain as orchestration framework?

**Status:** ☐ Open · **Decider:** you · **Blocks:** P0-1 dependencies

The proposal states the pipeline "will be implemented in Python using LangChain as the
orchestration framework". This spec uses only `langchain_text_splitters`, inside the
`recursive` chunker.

**Recommendation: direct SDK calls, keep the text splitter.** Orchestration frameworks
abstract over exactly the parameters this project must vary and report. When RQ1 asks
"what did reranking cost in latency", you need the call sites, not a chain.

**If you take this:** amend the methodology to "Python, with LangChain text splitters
for the recursive chunking baseline". One sentence. Do not leave the stronger claim
standing.

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

## OD-5 — Ethics of interactive crawling

**Status:** ☐ **Open — highest priority** · **Decider:** supervisor · **Blocks:** P1-5

Your ethics section states the research uses "publicly available web content" with "no
human participants". True for passive scraping. Weaker once the crawler is **submitting
clicks to a live commercial system** — that is interaction with a third party's
production infrastructure, not observation of published content.

`blocked_control_patterns` is a blocklist. Blocklists leak. A button labelled "Continue"
on step 3 of a booking flow matches nothing in the pattern set.

**Required before any live interactive crawl:**

1. Written permission from both businesses, naming interactive crawling specifically
2. First runs against a local copy or staging environment you control
3. Ethics section amended to describe interaction, not just retrieval
4. `controls_blocked` in the manifest retained as the audit trail (`docs/05` §4)

**If permission is not obtainable:** set `interaction_probing: false` as the default,
and `C10` becomes a headline finding — *what passive crawling misses* — rather than an
ablation. That is a perfectly good outcome and costs the project nothing.

**Do not implement P1-5 against a live third-party site before this is settled.**

---

## OD-6 — Which two SME domains?

**Status:** ☐ Open · **Decider:** you + supervisor · **Blocks:** P5-2, test set construction

The proposal requires two SMEs from distinct industries, with scraping permitted. Your
supervisor's earlier note references "Tony and Stephanie's workflows" — are those the
two candidates?

**Selection criteria, in priority order:**

1. Scraping permitted (`robots.txt` plus written permission — see OD-5)
2. **Genuinely different content structure**, not just different industry. RQ4 tests
   generalisation across *content shape*: document length, vocabulary, information
   density, question type. Two service businesses with near-identical brochure sites
   would make RQ4 unanswerable regardless of industry labels.
3. Contains at least one real multi-step workflow (booking, application, enrolment) —
   otherwise the supervisor's entire direction has nothing to extract
4. Contains tabular content — otherwise `C7` has no signal
5. Has plausible public/private content division — otherwise RQ2 is synthetic

**Decide by end of W1.** Everything downstream is blocked on the corpus.

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
