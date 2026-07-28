"""Retrieval metrics — pure functions over lists, no I/O, no config (docs/04 §6, docs/06).

Every number in the thesis passes through here, so this module imports nothing from the rest
of the package and is testable in isolation. Two families:

- **Page-level** (docs/06 §1): relevance by matching a retrieved chunk's ``source_url`` to a
  gold ``source_page``, normalised and substring-tolerant, with the bare-domain exact-match
  exception (a root-only gold must not wildcard-match every page).
- **Answer-span** (docs/06 §2.1): a chunk is answer-relevant only if the answer's *usable
  unit* co-occurs in it — every declared component present (AND), each component satisfied by
  any of its alternatives (OR). This sees intra-page chunking damage that page-level cannot.
"""

from __future__ import annotations

from urllib.parse import urlsplit

# --------------------------------------------------------------------------------------
# Page-level relevance (docs/06 §1)
# --------------------------------------------------------------------------------------


def _norm_url(url: str) -> str:
    return url.strip().lower().rstrip("/")


def _is_domain_root(gold: str) -> bool:
    """A gold that names only a site root (netloc with empty or ``/`` path) — must match exactly."""
    parts = urlsplit(gold.strip())
    return bool(parts.netloc) and parts.path in ("", "/")


def _url_match(retrieved: str, gold: str) -> bool:
    r, g = _norm_url(retrieved), _norm_url(gold)
    if not r or not g:
        return False
    if _is_domain_root(gold):
        return r == g  # bare-domain gold: no substring wildcard (docs/06 §1)
    return g in r or r in g


def _page_relevant(retrieved: str, gold: list[str]) -> bool:
    return any(_url_match(retrieved, g) for g in gold)


def precision_at_k(retrieved: list[str], gold: list[str], k: int) -> float:
    topk = retrieved[:k]
    if not topk:
        return 0.0
    return sum(_page_relevant(r, gold) for r in topk) / len(topk)


def recall_at_k(retrieved: list[str], gold: list[str], k: int) -> float:
    if not gold:
        return 0.0
    topk = retrieved[:k]
    return sum(any(_url_match(r, g) for r in topk) for g in gold) / len(gold)


def mrr(retrieved: list[str], gold: list[str]) -> float:
    for rank, r in enumerate(retrieved, start=1):
        if _page_relevant(r, gold):
            return 1.0 / rank
    return 0.0


def hit_rate_at_k(retrieved: list[str], gold: list[str], k: int) -> float:
    return 1.0 if any(_page_relevant(r, gold) for r in retrieved[:k]) else 0.0


# --------------------------------------------------------------------------------------
# Answer-span relevance (docs/06 §2.1)
# --------------------------------------------------------------------------------------

# A usable unit is `list[component]`; each component is `list[alternative]`.
# Relevant iff EVERY component has AT LEAST ONE alternative present (AND across, OR within).
Components = list[list[str]]


def _norm_text(text: str) -> str:
    """Casefold + collapse whitespace. Deliberately literal — no numeric canonicalisation, so a
    match is exactly what a reader can see (docs/06 §2.1)."""
    return " ".join(text.split()).casefold()


def is_answer_relevant(chunk_text: str, components: Components) -> bool:
    if not components:
        return False
    text = _norm_text(chunk_text)
    return all(any(_norm_text(alt) in text for alt in component) for component in components)


def answer_hit_at_k(chunk_texts: list[str], components: Components, k: int) -> float | None:
    """1.0 if any of the top-k chunks is answer-relevant; None when no usable unit is declared.

    None (not 0.0) means "not answer-scored" — only questions with an authored unit count,
    so prose/list questions without a single-place answer are excluded rather than penalised.
    """
    if not components:
        return None
    return 1.0 if any(is_answer_relevant(t, components) for t in chunk_texts[:k]) else 0.0


def answer_precision_at_k(chunk_texts: list[str], components: Components, k: int) -> float | None:
    if not components:
        return None
    topk = chunk_texts[:k]
    if not topk:
        return 0.0
    return sum(is_answer_relevant(t, components) for t in topk) / len(topk)
