"""SPIKE — thin vertical slice to a first retrieval number (Wyatt, C0-baseline).

This package is a deliberate spike, not production pipeline code. It proves the spine
end-to-end — typed chunking → MiniLM embedding → real Qdrant → dense retrieval → scored
metrics — on ONE domain and ONE config, to find where the pipeline breaks before the full
matrix is built. It is intentionally minimal and will be superseded by the real Phase 2/3/4
modules in their proper homes (``ingestion/chunking/typed.py``, ``store/vector.py``,
``retrieval/dense.py``, ``evaluation/metrics.py``). Delete this package once those land.

Marked SPIKE throughout so it is never mistaken for the hardened path.
"""