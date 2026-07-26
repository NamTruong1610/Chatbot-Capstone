"""SPIKE — page-level retrieval metrics (docs/06 §1–2, thin slice only).

Pure functions over lists of source URLs, mirroring what the real ``evaluation/metrics.py``
will own. Relevance is page-level (docs/06 §1): a retrieved source is relevant if it
matches a gold ``source_page``, normalised (lowercase, trailing slash stripped) and
accepting substring containment in either direction.

Never invent a metric (CLAUDE.md rule 5) — these four are exactly docs/06 §2.
"""

from __future__ import annotations

from urllib.parse import urlsplit


def _norm(url: str) -> str:
    return url.strip().lower().rstrip("/")


def _is_domain_root(gold: str) -> bool:
    """True when a gold entry names only a site root (netloc with empty or ``/`` path).

    Such an entry ('https://x.test/') normalises to the bare domain, which is a substring
    of *every* page URL on that site — so the generic substring rule would score every
    retrieved chunk as relevant. These must match the root exactly instead.
    """
    parts = urlsplit(gold.strip())
    return bool(parts.netloc) and parts.path in ("", "/")


def _match(retrieved: str, gold: str) -> bool:
    r, g = _norm(retrieved), _norm(gold)
    if not r or not g:
        return False
    if _is_domain_root(gold):
        # Fail the wildcard: a bare-domain gold hits only the site root, never a sub-page.
        return r == g
    return g in r or r in g


def _relevant(retrieved: str, gold: list[str]) -> bool:
    return any(_match(retrieved, g) for g in gold)


def precision_at_k(retrieved: list[str], gold: list[str], k: int) -> float:
    """|{r in R[:k] : r relevant}| / |R[:k]|."""
    topk = retrieved[:k]
    if not topk:
        return 0.0
    return sum(_relevant(r, gold) for r in topk) / len(topk)


def recall_at_k(retrieved: list[str], gold: list[str], k: int) -> float:
    """|{g in G : g in R[:k]}| / |G| — fraction of gold pages present in the top-k."""
    if not gold:
        return 0.0
    topk = retrieved[:k]
    found = sum(any(_match(r, g) for r in topk) for g in gold)
    return found / len(gold)


def mrr(retrieved: list[str], gold: list[str]) -> float:
    """1 / rank of the first relevant retrieved source, else 0."""
    for rank, r in enumerate(retrieved, start=1):
        if _relevant(r, gold):
            return 1.0 / rank
    return 0.0


def hit_rate_at_k(retrieved: list[str], gold: list[str], k: int) -> float:
    """1.0 if any relevant source in R[:k], else 0.0."""
    return 1.0 if any(_relevant(r, gold) for r in retrieved[:k]) else 0.0