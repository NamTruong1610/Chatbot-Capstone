"""Evaluation layer (docs/04 §6): ingest orchestration, retrieval debug, and (Stage 2) scoring.

May import all pipeline layers; pipeline code must never import this. ``metrics`` (Stage 2)
stays pure — no imports from the rest of the package.
"""
