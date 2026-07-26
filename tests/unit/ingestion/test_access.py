"""FR-ACL-02 access-level assignment from URL patterns (label-but-don't-filter)."""

from __future__ import annotations

from chatbot.config.schema import AccessControlConfig
from chatbot.ingestion.access import assign_access

CFG = AccessControlConfig()  # defaults: private_url_patterns includes /staff, /dashboard, ...


def test_private_url_pattern_labels_private_and_records_the_rule() -> None:
    level, rule = assign_access("https://wyatt.nsw.edu.au/staff-dashboard", CFG)
    assert level == "private"
    assert rule.startswith("url_pattern:/staff")  # first matching pattern wins


def test_public_page_takes_the_default_with_default_rule() -> None:
    level, rule = assign_access("https://wyatt.nsw.edu.au/courses", CFG)
    assert level == "public"
    assert rule == "default"


def test_matching_is_case_insensitive() -> None:
    level, _ = assign_access("https://wyatt.nsw.edu.au/Internal/Reports", CFG)
    assert level == "private"
