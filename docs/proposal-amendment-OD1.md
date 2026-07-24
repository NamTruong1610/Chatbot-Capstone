# Proposal amendment — vector store (OD-1)

For the methodology section of the proposal. Your current text derives the L2/cosine
equivalence in order to justify **FAISS**. The derivation is correct and worth keeping;
what changes is what it is doing there. It no longer justifies the choice of store — it
justifies why the choice of store is *free*, which lets you choose on the criterion that
actually matters for RQ2.

---

## What to cut

The two formula blocks and surrounding prose currently running from *"At the retrieval
stage, the system measures semantic similarity…"* through *"…The system returns the top-k
nearest chunks as retrieval candidates."*

Keep the cosine formula. Cut the standalone L2 formula and the FAISS framing around it.

---

## Replacement text

> At the retrieval stage, the system measures semantic similarity between the query
> embedding and each chunk embedding using cosine similarity:
>
> cos(a, b) = (a · b) / (‖a‖ × ‖b‖)
>
> where a · b is the dot product of the two vectors and ‖a‖ and ‖b‖ are their magnitudes.
> Values range from 0 (no similarity) to 1 (identical meaning). This is the standard
> similarity measure reported in the RAG literature, and the metric under which the
> vector store ranks candidates.
>
> The knowledge base is implemented in Qdrant rather than FAISS. The determining factor
> is RQ2. Serving both public and private users from a single knowledge base requires
> every retrieval to be scoped to the requesting role, which means filtering on chunk
> metadata — `domain_id` for tenant isolation and `access_level` for role scoping — on
> every query. Qdrant applies such filters server-side, within the same call that
> performs the vector search, so a chunk the requesting role may not see is never scored
> and never enters the candidate set. Access control is therefore enforced structurally
> rather than by discarding impermissible results after retrieval. This distinction is
> the subject of RQ2: Lorenzo et al. (2025) report 85% accuracy and 89% F1 for ARBITER
> precisely because it classifies retrieved content post hoc, and the present study
> treats pre-filtering and post-filtering as competing experimental conditions rather
> than assuming either.
>
> The change of store does not affect comparability with the preliminary retrieval test
> reported in Appendix A, which used FAISS and ranked by L2 (Euclidean) distance. The
> embedding model, `all-MiniLM-L6-v2`, produces normalised vectors, and for normalised
> vectors ranking by L2 distance and ranking by cosine similarity are equivalent: the
> chunk nearest by L2 is the chunk highest-scoring by cosine. The retrieved set is
> therefore unchanged by the substitution, and the Appendix A condition can be replicated
> exactly as a chunking baseline in the main study. Absolute distance values reported in
> Appendix A are not directly comparable with cosine similarity scores reported later;
> the rankings they induce are.
>
> The system returns the top-k highest-scoring chunks as retrieval candidates, where k is
> a configurable parameter varied as part of the experimental design.

---

## Also worth adding

If you have room, one sentence in the contribution section. RQ2 currently promises to
evaluate access-scoped retrieval; naming the mechanism sharpens the claim:

> By enforcing role scoping as an indexed pre-filter rather than a post-retrieval
> classification, this study tests whether the residual leakage risk reported in
> enterprise access-control frameworks can be eliminated at SME scale, at the cost of a
> dependency on correct metadata assignment at ingest.

That sentence states a real trade-off with a measurable cost side, which is what turns
RQ2 from an implementation detail into a contribution.

---

## Change log for your supervisor

Short version for the Friday update:

- Vector store changed from FAISS to Qdrant. Reason: RQ2 needs metadata-filtered
  retrieval on every query, which Qdrant does server-side and FAISS would require to be
  hand-built.
- No effect on Appendix A comparability — MiniLM vectors are normalised, so L2 and cosine
  rank identically.
- Methodology paragraph rewritten accordingly; the L2 derivation is retained but
  repurposed as the comparability argument rather than the justification for FAISS.
