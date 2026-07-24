# 06 — Evaluation Protocol

Metrics defined here are the only metrics. Do not add one without raising it in
`docs/08-open-decisions.md` first (CLAUDE.md rule 5). Every number in the thesis passes
through `evaluation/metrics.py`, which is pure functions with no I/O.

---

## 1. Relevance

Judged at **page level**: a retrieved chunk is relevant if its `source_url` (or
`filename` for uploads) matches a page listed in the test case's `source_page`.

Page-level rather than chunk-level, because chunk ids change every time chunking changes,
and chunking is an experimental arm (`C5`–`C8`). Chunk-level ground truth would have to
be rebuilt for every chunking config — infeasible at 40 questions × 2 domains, and it
would make chunking arms non-comparable with each other.

Matching is normalised (lowercase, trailing slash stripped) and accepts substring
containment in either direction, so `page_1.txt` matches a full URL ending in that
identifier.

**Limitation to state in chapter 5:** page-level relevance cannot distinguish "retrieved
the right page, wrong section" from "retrieved the right section". It therefore
*understates* the value of any technique that improves within-page precision — which
plausibly includes reranking. Flag this when interpreting RQ1.

---

## 2. Retrieval metrics

Let `R` = retrieved sources in rank order, `G` = gold sources, `k` = `retrieval.top_k`.

| Metric | Definition | Answers |
|---|---|---|
| **precision@k** | `\|{r ∈ R[:k] : r relevant}\| / \|R[:k]\|` | How much of what we returned was useful |
| **recall@k** | `\|{g ∈ G : g ∈ R[:k]}\| / \|G\|` | How much of the answer we found |
| **MRR** | `1 / rank of first relevant`, else `0` | How near the top the answer landed |
| **hit_rate@k** | `1` if any relevant in `R[:k]`, else `0` | Could the generator have answered at all |
| **latency_ms** | Wall clock, retrieval only | What the quality cost |

`hit_rate` is the metric to lead with for an SME audience. precision@5 improving from
0.42 to 0.51 means little to a business owner; "the answer was available 9 times in 10
instead of 8" means something. Report both.

`recall@k` is the metric that `multi_chunk` questions turn on, and the one chunking
strategy should move most.

---

## 3. Abstention scoring

Some questions the system is **supposed** to fail. Scoring those as retrieval misses
penalises correct behaviour.

A case is routed to abstention scoring (`scored_as: "abstention"`) when either:

- `question_type == "out_of_scope"` — the answer is not in the corpus, or
- `access_level == "private"` **and** `role == "customer"` — the answer exists but this
  role may not have it

For these, retrieval metrics are written as **null, not zero**. Zero would drag the
group mean down and make a correctly-behaving configuration look worse than a leaky one.

Scoring:

```
should_abstain = True
did_abstain    = abstention phrase present in the generated answer
correct        = should_abstain == did_abstain
```

Detection is exact-substring against `generation.abstention_phrase`. Brittle by design —
a model that paraphrases the refusal is not following the prompt, and that is itself a
finding worth reporting rather than papering over with fuzzy matching.

Report **abstention accuracy** split by cause. Failing to abstain on out-of-scope
(hallucination) and failing to abstain on private (leakage) are different failures with
different consequences; a combined number hides which one is happening.

---

## 4. Access control metrics (RQ2)

| Metric | Definition |
|---|---|
| **leaked_chunks** | Count of `private` chunks returned to a `customer` role. **Raw count.** |
| **leak_rate** | Leaked chunks / total chunks returned to customers. Reported *alongside*, never instead of. |
| **role_precision** | Of chunks returned, fraction the role was permitted |
| **role_recall** | Of permitted chunks that were relevant, fraction returned |
| **over_restriction** | Admin queries where a permitted chunk was wrongly withheld |

**Why raw count.** A 2% leak rate is not 98% good. One leaked staff-only chunk is
deployment-blocking for an SME. Averaging it into a rate makes a catastrophic failure
look like a rounding error. Report the count, and if it is non-zero, the run failed —
say so in the table rather than reporting a mean around it.

`over_restriction` matters because it is the cost side of `prefilter`. A strategy that
leaks nothing by returning nothing is not a good strategy, and the comparison against
`postfilter` (`C11`) is only honest if both sides of the trade are measured.

---

## 5. Generation metrics (RAGAS)

Enabled by `evaluation.ragas_enabled`. Costs one LLM call per question per config, so
the default sweep is retrieval-only.

| Metric | What it measures |
|---|---|
| `faithfulness` | Are the answer's claims supported by the retrieved context |
| `answer_relevancy` | Does the answer address the question |
| `context_precision` | Are the retrieved chunks actually relevant to the question |

**Record the judge model and its version in `run.json`.** LLM-as-judge scores are not
comparable across judge models, and a silent judge upgrade mid-project would invalidate
every cross-configuration comparison. Pin it and do not change it after the first run.

---

## 6. Comparison procedure

### 6.1 The unit of comparison is the paired question

Never compare two configurations by their group means alone. Every configuration runs
the same test set, so comparisons are paired: for each question, the delta between
config A and config B.

For each pair report:

- **n** — number of paired questions
- **Median delta** and IQR
- **Wins / losses / ties** — the most legible summary for a non-statistical reader
- **Wilcoxon signed-rank p-value** — paired, non-parametric, appropriate for bounded
  non-normal metrics at n≈40
- **Effect size** — rank-biserial correlation, or Cliff's delta

Bonferroni-correct across the configurations compared within one RQ, and say so.

### 6.2 Reporting standard

A finding is reportable as an improvement only if the direction is consistent across
**both domains**. A gain in one domain and a loss in the other is an RQ4 finding about
domain sensitivity, not an RQ1 finding about retrieval — and should be written up as
such. Gao et al. (2025) found exactly this pattern across three domains, so expect it.

### 6.3 Null results

A null result is a valid finding and must be reported as one. The proposal already
commits to this for RQ3; it applies equally to RQ1 and the chunking arms.

Given n≈40 per domain, this study can detect large effects, not small ones. When a
comparison is null, report the confidence interval and state the minimum effect the
design could have detected. "No significant difference" and "no difference" are not the
same claim, and a marker will look for that distinction.

---

## 7. Experimental procedure per RQ

### RQ1 — retrieval architecture

- **Configs:** `C0-baseline` (dense), `C1-hybrid`, `C2-hybrid-rerank`; plus `C3` (fusion)
  and `C4` (top_k) as secondary
- **Held constant:** chunking, embedding, ACL, generation, corpus
- **Index:** one ingest serves all three — retrieval mode does not change the index
- **Primary metrics:** hit_rate@5, recall@5, MRR, latency_ms
- **Paired comparisons:** C0→C1, C1→C2, C0→C2
- **Report:** quality gain *and* latency cost per stage. An SME needs both to choose.

### RQ2 — access control

- **Configs:** `C0` (prefilter), `C11` (postfilter), `C12` (none, harness-only control)
- **Roles:** every question run under both `customer` and `admin`
- **Primary metrics:** leaked_chunks, over_restriction, abstention accuracy on private
  cases, role_precision/recall
- **`C12` establishes the ceiling** — how much would leak with no controls at all. Without
  it, "zero leakage under prefilter" is unfalsifiable, because it might be that no private
  content was retrievable anyway.
- **Any non-zero leak under `C0` is a failed run.** Investigate `access_rule` first —
  the cause is almost certainly ingest mislabelling, not retrieval.

### RQ3 — fine-tuning

- **Configs:** best RQ1 config vs `C13-finetuned` (same retrieval, tuned generator)
- **Held constant:** retrieval, chunking, corpus, prompt
- **Primary metrics:** RAGAS faithfulness and answer_relevancy, abstention accuracy
- **Secondary:** `C14-prompt-permissive` isolates how much grounding comes from the prompt
  rather than the model — run it before concluding anything about fine-tuning
- **Report training cost:** hours, VRAM peak, dataset size. RQ3's actual question for an
  SME is not "does it help" but "does it help enough to be worth this".

### RQ4 — generalisation

- **Configs:** all of the above, both domains
- **Grouping:** `domain_id × config_id × question_type`
- **Primary question:** does the ranking of configurations hold across domains
- **Report a rank-correlation** between the two domains' configuration orderings. If
  configurations rank differently by domain, that is the RQ4 result — and it directly
  supports Gao et al. (2025).

### Chunking (unplanned in the proposal, required by Appendix A)

- **Configs:** `C0` (typed) vs `C5` (fixed, Appendix A replication), `C6` (recursive),
  `C7` (table split), `C8` (no breadcrumb)
- **Each needs its own ingest** — chunking changes the index (`docs/04` §5)
- **Primary metrics:** recall@5 on `multi_chunk`, hit_rate on questions whose gold source
  contains a table
- **Watch for:** if `|C0 − C5|` exceeds `|C0 − C2|`, chunking dominates retrieval
  architecture at SME scale. That would be the thesis's most useful finding, and it
  should lead chapter 5 rather than sit in an appendix.

---

## 8. Reproducibility requirements

Every run writes `run.json` with resolved config, config hash, git SHA, index
fingerprints, library versions, hardware summary, and wall time (`docs/05` §5.4).

- Temperature 0.0 for all evaluation runs
- Seeds fixed for any stochastic operation
- Results append-only; a re-run writes a new timestamped directory
- Raw corpora archived at collection time and never regenerated (FR-CRAWL-09)

Re-running an identical config on an identical corpus must produce identical metrics
(NFR-03). Add a CI check that does this on a fixture corpus — if it ever fails, some
parameter escaped the config system and every result since is suspect.

---

## 9. Threats to validity — write these up, do not hide them

| Threat | Mitigation | Residual |
|---|---|---|
| Test set built by the same person who built the pipeline | Construct test sets from the corpus *before* tuning; freeze before first run | Author bias remains; acknowledge |
| Page-level relevance understates within-page precision | Stated in §1 | Under-credits reranking |
| n≈40 per domain | Paired tests, effect sizes, CIs | Small effects undetectable |
| Two domains only | Both chosen from distinct industries | Cannot claim general portability |
| RAGAS uses an LLM judge | Pin judge model, record version | Judge shares failure modes with the generator |
| AI-synthesised test pairs (contingency in the proposal) | Manual validation of every synthesised pair; flag them in `notes` | Synthesised questions may favour retrievable phrasings — **report the synthesised proportion** |
| Websites change mid-project | Archive raw crawl at collection | Results describe the site as of the crawl date |
