"""AccessStrategy: role→levels mapping (fail-closed), and enforce as a counting backstop.

The security property is double-guarded (docs/04 §3): prefilter excludes impermissible chunks
server-side, and enforce is the redundant post-retrieval assertion that COUNTS any leak (FR-ACL-07
/ FR-ACL-08). These unit tests pin the strategy logic; the end-to-end isolation proof (a customer
query that would rank a private tracer first) is in test_chat_pipeline_acl.py.
"""

from __future__ import annotations

import pytest
from chatbot.retrieval.acl import build_access_strategy

from chatbot.config.schema import AccessControlConfig, AccessLevel
from chatbot.config.schema import AccessStrategy as StrategyEnum
from chatbot.retrieval.base import RetrievedChunk

TRACER = "WYT-AG-0447"


def _chunk(level: str, text: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"c-{level}", source_url="https://x/p", text=text, score=0.9, rank=1,
        access_level=level, payload={},
    )


def _cfg(strategy: StrategyEnum = StrategyEnum.prefilter) -> AccessControlConfig:
    return AccessControlConfig(
        strategy=strategy,
        role_map={
            "customer": [AccessLevel.public],
            "staff": [AccessLevel.public, AccessLevel.private],
        },
    )


def test_levels_for_maps_roles_and_fails_closed_on_unknown() -> None:
    s = build_access_strategy(_cfg())
    assert s.levels_for("customer") == {"public"}
    assert s.levels_for("staff") == {"public", "private"}
    assert s.levels_for("intruder") == set()  # fail-closed: unknown role sees nothing (rule 4)
    assert s.prefilter() is True


def test_prefilter_enforce_backstops_and_counts_a_leak() -> None:
    s = build_access_strategy(_cfg())
    chunks = [_chunk("public", "public info"), _chunk("private", f"agent {TRACER} is secret")]

    permitted, leaked = s.enforce(chunks, "customer")
    assert leaked == 1  # the private chunk is a leak, counted (FR-ACL-08 raw count)
    assert all(c.access_level == "public" for c in permitted)
    assert not any(TRACER in c.text for c in permitted)  # tracer never survives to a customer

    permitted, leaked = s.enforce(chunks, "staff")
    assert leaked == 0 and len(permitted) == 2  # staff may see both — nothing withheld


def test_none_strategy_counts_but_does_not_drop_and_is_harness_gated() -> None:
    # FR-ACL-05: `none` establishes the leakage ceiling and must be impossible to select
    # outside the evaluation harness.
    with pytest.raises(ValueError, match="harness"):
        build_access_strategy(_cfg(StrategyEnum.none))

    s = build_access_strategy(_cfg(StrategyEnum.none), harness=True)
    assert s.prefilter() is False
    permitted, leaked = s.enforce([_chunk("public", "x"), _chunk("private", TRACER)], "customer")
    assert leaked == 1 and len(permitted) == 2  # counts the leak but does NOT drop it (ceiling)


def test_postfilter_does_not_prefilter_but_enforce_drops() -> None:
    s = build_access_strategy(_cfg(StrategyEnum.postfilter))
    assert s.prefilter() is False  # retrieve unfiltered, drop after (FR-ACL-04)
    permitted, leaked = s.enforce([_chunk("public", "x"), _chunk("private", TRACER)], "customer")
    assert leaked == 1 and all(c.access_level == "public" for c in permitted)
