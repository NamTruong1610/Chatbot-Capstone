"""ConversationStore contract (Phase 8, FR-API-01/03; OD-16).

The same contract runs against both implementations: the in-memory store (always, CI-safe) and
the Postgres store (only when CHATBOT_POSTGRES_DSN points at a reachable database — otherwise
skipped, the same way the Playwright rendering tests skip when no browser is present). Writing the
contract once, parametrised over the fixture, is what guarantees the fake the API tests rely on
behaves like the real store.

The test with teeth is ``test_scope_mismatch_is_rejected``: opening a conversation under a
different role must fail closed, so a customer session can never resume a staff conversation and
inherit its private history (RQ2 isolation, extended into the conversation layer).
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

import pytest

from chatbot.store.conversation import (
    ASSISTANT,
    USER,
    ConversationScopeError,
    InMemoryConversationStore,
    PostgresConversationStore,
)

SCHEMA_SQL = (Path(__file__).resolve().parents[3] / "db" / "conversation_schema.sql").read_text()


def _postgres_available() -> bool:
    dsn = os.environ.get("CHATBOT_POSTGRES_DSN")
    if not dsn:
        return False
    try:
        PostgresConversationStore(dsn).ensure_schema(SCHEMA_SQL)
        return True
    except Exception:
        return False


requires_postgres = pytest.mark.skipif(
    not _postgres_available(),
    reason="CHATBOT_POSTGRES_DSN unset or unreachable — Postgres contract tests skipped",
)


@pytest.fixture(
    params=[
        "memory",
        pytest.param("postgres", marks=requires_postgres),
    ]
)
def store(request: Any) -> Any:
    if request.param == "memory":
        return InMemoryConversationStore()
    pg = PostgresConversationStore(os.environ["CHATBOT_POSTGRES_DSN"])
    pg.ensure_schema(SCHEMA_SQL)
    return pg  # unique conversation ids per test keep a shared DB from cross-contaminating


def _cid() -> str:
    return uuid.uuid4().hex


def test_open_is_get_or_create_and_returns_scope(store: Any) -> None:
    cid = _cid()
    first = store.open_conversation(cid, "wyatt-edu", "customer")
    assert (first.conversation_id, first.domain_id, first.role) == (cid, "wyatt-edu", "customer")
    again = store.open_conversation(cid, "wyatt-edu", "customer")  # idempotent
    assert again == first


def test_scope_mismatch_is_rejected(store: Any) -> None:
    # TEETH: a conversation opened as customer cannot be reopened as staff — fail closed, so a
    # customer can never replay a staff conversation's (private) history.
    cid = _cid()
    store.open_conversation(cid, "wyatt-edu", "customer")
    with pytest.raises(ConversationScopeError):
        store.open_conversation(cid, "wyatt-edu", "staff")
    with pytest.raises(ConversationScopeError):
        store.open_conversation(cid, "austral-eng", "customer")  # domain mismatch too


def test_messages_get_incrementing_turn_indexes(store: Any) -> None:
    cid = _cid()
    store.open_conversation(cid, "wyatt-edu", "customer")
    u = store.append_message(cid, sender=USER, content="Tell me about the Diploma of Business")
    a = store.append_message(cid, sender=ASSISTANT, content="A 12-month course.", grounded=True)
    assert (u.turn_index, a.turn_index) == (0, 1)


def test_recent_exchanges_pairs_completed_turns_only(store: Any) -> None:
    cid = _cid()
    store.open_conversation(cid, "wyatt-edu", "customer")
    store.append_message(cid, sender=USER, content="Tell me about the Diploma of Business")
    store.append_message(cid, sender=ASSISTANT, content="A 12-month course.", grounded=True)
    store.append_message(cid, sender=USER, content="how much is it?")  # dangling — no reply yet

    exchanges = store.recent_exchanges(cid, limit_turns=8)
    assert len(exchanges) == 1  # the unpaired trailing user turn contributes nothing
    assert exchanges[0].user == "Tell me about the Diploma of Business"
    assert exchanges[0].assistant == "A 12-month course."


def test_recent_exchanges_is_bounded_and_oldest_first(store: Any) -> None:
    cid = _cid()
    store.open_conversation(cid, "wyatt-edu", "customer")
    for i in range(5):
        store.append_message(cid, sender=USER, content=f"q{i}")
        store.append_message(cid, sender=ASSISTANT, content=f"a{i}")

    exchanges = store.recent_exchanges(cid, limit_turns=2)
    assert [e.user for e in exchanges] == ["q3", "q4"]  # last two, oldest of the two first


def test_list_messages_round_trips_provenance(store: Any) -> None:
    # search_query (the rewrite, decision 7), grounded, and sources all persist and read back.
    cid = _cid()
    store.open_conversation(cid, "wyatt-edu", "customer")
    store.append_message(cid, sender=USER, content="how much is it?")
    store.append_message(
        cid, sender=ASSISTANT, content="The fee is $11,500.", grounded=True,
        sources=["https://wyatt/courses"], search_query="How much is the Diploma of Business?",
    )

    msgs = store.list_messages(cid)
    assert [m.sender for m in msgs] == [USER, ASSISTANT]
    assert msgs[0].grounded is None and msgs[0].sources == []
    assert msgs[1].grounded is True
    assert msgs[1].sources == ["https://wyatt/courses"]
    assert msgs[1].search_query == "How much is the Diploma of Business?"


def test_append_to_unopened_conversation_is_an_error() -> None:
    # In-memory-specific: the fake refuses an append with no conversation. On Postgres the foreign
    # key enforces the same invariant (a different exception), so this asserts only the fake, which
    # is the surface the API tests stub against.
    from chatbot.store.conversation import ConversationError

    store = InMemoryConversationStore()
    with pytest.raises(ConversationError):
        store.append_message("ghost", sender=USER, content="hi")


# --- list_conversations (Phase 12) ---


def _dom() -> str:
    # A unique domain per test isolates the scoped list on a shared Postgres.
    return f"d-{uuid.uuid4().hex[:8]}"


def _converse(store: Any, cid: str, domain: str, role: str, user_text: str) -> None:
    store.open_conversation(cid, domain, role)
    store.append_message(cid, sender=USER, content=user_text)
    store.append_message(cid, sender=ASSISTANT, content=f"reply to: {user_text}")


def test_list_conversations_is_scoped_and_most_recent_first(store: Any) -> None:
    domain = _dom()
    first, second = _cid(), _cid()
    _converse(store, first, domain, "customer", "first question")
    _converse(store, second, domain, "customer", "second question")  # more recently active
    _converse(store, _cid(), domain, "staff", "staff question")  # different role — excluded
    _converse(store, _cid(), _dom(), "customer", "other domain")  # different domain — excluded

    listed = store.list_conversations(domain, "customer")
    assert [c.session_id for c in listed] == [second, first]  # most recent first, scoped
    assert all(c.domain_id == domain and c.role == "customer" for c in listed)


def test_list_conversation_summary_fields(store: Any) -> None:
    domain = _dom()
    cid = _cid()
    store.open_conversation(cid, domain, "customer")
    store.append_message(cid, sender=USER, content="How much is the Diploma of Business?")
    store.append_message(cid, sender=ASSISTANT, content="The fee is $11,500.")

    (summary,) = store.list_conversations(domain, "customer")
    assert summary.title == "How much is the Diploma of Business?"  # first user message
    assert summary.preview == "The fee is $11,500."  # last message
    assert summary.message_count == 2
    assert summary.updated_at  # a timestamp is present


def test_list_conversation_title_is_truncated(store: Any) -> None:
    domain = _dom()
    cid = _cid()
    long_q = "why " * 60  # far longer than the 80-char title limit
    store.open_conversation(cid, domain, "customer")
    store.append_message(cid, sender=USER, content=long_q)
    store.append_message(cid, sender=ASSISTANT, content="because")

    (summary,) = store.list_conversations(domain, "customer")
    assert summary.title.endswith("…")
    assert len(summary.title) <= 81  # 80 chars + the ellipsis


def test_empty_conversation_is_excluded(store: Any) -> None:
    domain = _dom()
    store.open_conversation(_cid(), domain, "customer")  # opened, no messages
    assert store.list_conversations(domain, "customer") == []


def test_conversation_with_no_user_message_is_untitled(store: Any) -> None:
    domain = _dom()
    cid = _cid()
    store.open_conversation(cid, domain, "customer")
    store.append_message(cid, sender=ASSISTANT, content="a system note with no user turn")

    (summary,) = store.list_conversations(domain, "customer")
    assert summary.title == "(untitled)"
