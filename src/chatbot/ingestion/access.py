"""Access-level assignment at ingest (FR-ACL-02).

Assigns ``access_level`` and records which rule fired (``access_rule``, docs/05 §1), in the
precedence order FR-ACL-02 fixes: explicit per-document override → URL-pattern rule → default.
Only the URL-pattern and default tiers exist today; there are no per-document overrides yet.

Why assign now and not when filtering lands (RQ2): labels must be frozen in the index from
the first ingest. If they were added later, turning on filtering would silently change what
each role can retrieve and break baseline reproducibility. So the pipeline labels every chunk
now; retrieval simply does not filter on the label yet (label-but-don't-filter).
"""

from __future__ import annotations

from chatbot.config.schema import AccessControlConfig


def assign_access(
    source_url: str, cfg: AccessControlConfig, *, explicit_level: str | None = None
) -> tuple[str, str]:
    """Return ``(access_level, access_rule)`` for a chunk, in FR-ACL-02 precedence order.

    1. **Explicit per-document override** — an uploaded page may state its own ``access_level``
       (e.g. staff-only content that is not URL-addressable); it wins over everything.
    2. **URL pattern** — a page whose URL contains any ``private_url_patterns`` entry (e.g.
       ``/staff-dashboard`` matches ``/staff``) is ``private``, tagged with the pattern that fired.
    3. **Default** — ``default_level``.

    Fail-closed is not in play here — this assigns a label, it does not grant access — but the
    first matching rule wins for a stable, recorded assignment (docs/05 §1 ``access_rule``).
    """
    if explicit_level is not None:
        return explicit_level, "explicit_override"
    url = source_url.lower()
    for pattern in cfg.private_url_patterns:
        if pattern.lower() in url:
            return "private", f"url_pattern:{pattern}"
    return cfg.default_level.value, "default"
