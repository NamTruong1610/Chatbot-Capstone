"""Conversation history as the pipeline sees it: an ordered list of completed exchanges.

A ``Turn`` is one user→assistant exchange. This is the *in-memory* shape threaded through the
pipeline (retrieval-rewrite and generation), deliberately decoupled from how conversations are
stored: the Postgres layer (Phase 8, Step 3) persists individual messages and reconstructs
``Turn`` objects to hand in. Keeping this a plain frozen value — no ids, no timestamps, no store
coupling — is what lets the pipeline stay pure and the single-shot eval path pass ``history=None``
and behave exactly as before (the property that protects the RQ numbers).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Turn:
    """One completed exchange: ``user`` is what the person asked, ``assistant`` what we replied."""

    user: str
    assistant: str
