"""Access-control strategies (FR-ACL-03/04/05/07): role→levels + the leak-counting backstop.

Three registered strategies, one interface, no branching in the retriever (docs/04 §3). The
security property is **double-guarded**:

- ``prefilter`` — the pipeline passes the role's permitted levels to the retriever, so the dense
  arm filters server-side (FR-STORE-04) and impermissible chunks are never scored. Its
  ``enforce`` is the redundant post-retrieval assertion (FR-ACL-07): in a correct run it drops
  nothing; if it ever drops, that is a real leak from some arm — it logs an error and still
  drops, so the barrier holds regardless of which arm produced the chunk.
- ``postfilter`` — retrieve unfiltered, then ``enforce`` drops impermissible (FR-ACL-04).
- ``none`` — no filtering; ``enforce`` COUNTS the leak but does not drop it (the leakage ceiling,
  FR-ACL-05). It is **harness-only**: ``build_access_strategy`` refuses to build it unless the
  caller is the evaluation harness.

``levels_for`` fails **closed** (CLAUDE.md rule 4): an unknown role maps to the empty set, so it
can retrieve nothing — never a silent fall-through to ``public``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol, TypeVar, runtime_checkable

from chatbot.config.schema import AccessControlConfig
from chatbot.retrieval.base import RetrievedChunk

logger = logging.getLogger(__name__)


@runtime_checkable
class AccessStrategy(Protocol):
    def __init__(self, cfg: AccessControlConfig) -> None: ...
    def levels_for(self, role: str) -> set[str]: ...
    def prefilter(self) -> bool: ...
    def enforce(
        self, chunks: list[RetrievedChunk], role: str
    ) -> tuple[list[RetrievedChunk], int]: ...


ACCESS_STRATEGIES: dict[str, type[AccessStrategy]] = {}

_S = TypeVar("_S", bound=AccessStrategy)


def register_access_strategy(name: str) -> Callable[[type[_S]], type[_S]]:
    def deco(cls: type[_S]) -> type[_S]:
        ACCESS_STRATEGIES[name] = cls
        return cls

    return deco


class _RoleLevels:
    """Role→permitted-levels with fail-closed lookup, shared by every strategy."""

    def __init__(self, cfg: AccessControlConfig) -> None:
        self._role_map = {
            role: {level.value for level in levels} for role, levels in cfg.role_map.items()
        }

    def levels_for(self, role: str) -> set[str]:
        # Fail closed: an unmapped role sees nothing, rather than defaulting to public (rule 4).
        return set(self._role_map.get(role, set()))


def _partition(
    chunks: list[RetrievedChunk], allowed: set[str]
) -> tuple[list[RetrievedChunk], list[RetrievedChunk]]:
    permitted = [c for c in chunks if c.access_level in allowed]
    leaked = [c for c in chunks if c.access_level not in allowed]
    return permitted, leaked


@register_access_strategy("prefilter")
class PrefilterStrategy:
    def __init__(self, cfg: AccessControlConfig) -> None:
        self._roles = _RoleLevels(cfg)

    def levels_for(self, role: str) -> set[str]:
        return self._roles.levels_for(role)

    def prefilter(self) -> bool:
        return True

    def enforce(self, chunks: list[RetrievedChunk], role: str) -> tuple[list[RetrievedChunk], int]:
        permitted, leaked = _partition(chunks, self.levels_for(role))
        if leaked:
            # FR-ACL-07: under prefilter this must never fire. If it does, an arm leaked — log
            # loudly and still drop, so the barrier holds no matter which arm produced the chunk.
            logger.error(
                "prefilter backstop dropped %d impermissible chunk(s) for role %r — an arm leaked",
                len(leaked),
                role,
            )
        return permitted, len(leaked)


@register_access_strategy("postfilter")
class PostfilterStrategy:
    def __init__(self, cfg: AccessControlConfig) -> None:
        self._roles = _RoleLevels(cfg)

    def levels_for(self, role: str) -> set[str]:
        return self._roles.levels_for(role)

    def prefilter(self) -> bool:
        return False  # retrieve unfiltered; drop after ranking (FR-ACL-04)

    def enforce(self, chunks: list[RetrievedChunk], role: str) -> tuple[list[RetrievedChunk], int]:
        permitted, leaked = _partition(chunks, self.levels_for(role))
        return permitted, len(leaked)  # dropping here is expected — no error log


@register_access_strategy("none")
class NoneStrategy:
    def __init__(self, cfg: AccessControlConfig) -> None:
        self._roles = _RoleLevels(cfg)

    def levels_for(self, role: str) -> set[str]:
        return self._roles.levels_for(role)

    def prefilter(self) -> bool:
        return False

    def enforce(self, chunks: list[RetrievedChunk], role: str) -> tuple[list[RetrievedChunk], int]:
        # The leakage ceiling: count what a customer would see, but do NOT drop it (FR-ACL-05).
        _, leaked = _partition(chunks, self.levels_for(role))
        return chunks, len(leaked)


def build_access_strategy(cfg: AccessControlConfig, *, harness: bool = False) -> AccessStrategy:
    """Build the strategy named by ``cfg.strategy``. ``none`` is refused outside the harness.

    Fails loud on an unknown strategy (CLAUDE.md rule 2). ``none`` (FR-ACL-05) is the control that
    establishes the leakage ceiling and must be impossible to select outside the evaluation
    harness — so it is only built when ``harness=True``.
    """
    name = cfg.strategy.value
    if name == "none" and not harness:
        raise ValueError(
            "access_control.strategy='none' is harness-only (FR-ACL-05); it disables leak "
            "protection and cannot be built for serving."
        )
    try:
        cls = ACCESS_STRATEGIES[name]
    except KeyError:
        raise ValueError(
            f"no access strategy registered for {name!r}. Registered: {sorted(ACCESS_STRATEGIES)}"
        ) from None
    return cls(cfg)
