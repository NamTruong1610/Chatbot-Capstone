"""Conversation persistence (Phase 8, FR-API-01/03; OD-16): the live store for multi-turn chat.

A conversation is an ordered log of messages scoped by ``(domain_id, role)``, fixed when the
conversation is opened. Two implementations behind one Protocol: an in-memory store (CI, and the
default for tests) and a Postgres store (psycopg 3, lazy-imported). The API layer (Step 4) owns the
load→answer→persist orchestration; this module only reads and writes.

Deliberately decoupled from generation: the store speaks in its own ``Exchange`` value, never
``generation.history.Turn`` — importing generation here would invert the layering (``store`` may
import ``config`` only, docs/04 §layering). The trivial ``Exchange`` → ``Turn`` mapping lives in the
API layer, which sits above both.

Scope is fail-closed (decision 6, extending RQ2 isolation into the conversation layer): opening a
conversation under a different ``(domain_id, role)`` than it was created with raises rather than
replaying another scope's history.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

USER = "user"
ASSISTANT = "assistant"
_DSN_ENV = "CHATBOT_POSTGRES_DSN"


class ConversationError(RuntimeError):
    """A fault in the conversation store (bad scope, or the store cannot be reached/configured)."""


class ConversationScopeError(ConversationError):
    """A conversation was opened under a different (domain_id, role) than it was created with.

    Fail closed: never serve or extend a conversation for a scope it does not belong to, so a
    customer session cannot resume a staff conversation and inherit its private history.
    """


@dataclass(frozen=True)
class Conversation:
    """A conversation's fixed identity and scope."""

    conversation_id: str
    domain_id: str
    role: str


@dataclass(frozen=True)
class Message:
    """One stored message. ``grounded``/``sources``/``search_query`` are assistant provenance."""

    conversation_id: str
    turn_index: int
    sender: str  # USER | ASSISTANT
    content: str
    grounded: bool | None = None
    sources: list[str] = field(default_factory=list)
    search_query: str | None = None


@dataclass(frozen=True)
class Exchange:
    """One completed user→assistant exchange, reconstructed from the message log.

    The store's own history value — mapped to ``generation.history.Turn`` by the API layer so the
    store need not depend on generation.
    """

    user: str
    assistant: str


@runtime_checkable
class ConversationStore(Protocol):
    """Read/write a conversation log. Implementations: in-memory (tests/CI) and Postgres."""

    def open_conversation(self, conversation_id: str, domain_id: str, role: str) -> Conversation:
        """Get-or-create the conversation, enforcing its (domain_id, role) scope (fail closed)."""
        ...

    def append_message(
        self,
        conversation_id: str,
        *,
        sender: str,
        content: str,
        grounded: bool | None = None,
        sources: list[str] | None = None,
        search_query: str | None = None,
    ) -> Message:
        """Append a message at the next turn index and return it."""
        ...

    def recent_exchanges(self, conversation_id: str, *, limit_turns: int) -> list[Exchange]:
        """The most recent completed exchanges (bounded), oldest first — history for generation."""
        ...

    def list_messages(self, conversation_id: str) -> list[Message]:
        """Every message in order — backs the fetch-a-conversation endpoint."""
        ...


def _pair_exchanges(messages: list[Message]) -> list[Exchange]:
    """Pair each user message with the assistant reply that follows it, in order.

    A trailing user message with no reply yet (mid-request) contributes no exchange — only
    completed pairs become history, so the model never sees a dangling half-turn.
    """
    exchanges: list[Exchange] = []
    pending_user: str | None = None
    for msg in sorted(messages, key=lambda m: m.turn_index):
        if msg.sender == USER:
            pending_user = msg.content
        elif msg.sender == ASSISTANT and pending_user is not None:
            exchanges.append(Exchange(user=pending_user, assistant=msg.content))
            pending_user = None
    return exchanges


class InMemoryConversationStore:
    """Process-local store for CI and tests. Same contract as Postgres, no persistence."""

    def __init__(self) -> None:
        self._conversations: dict[str, Conversation] = {}
        self._messages: dict[str, list[Message]] = {}

    def open_conversation(self, conversation_id: str, domain_id: str, role: str) -> Conversation:
        existing = self._conversations.get(conversation_id)
        if existing is None:
            convo = Conversation(conversation_id, domain_id, role)
            self._conversations[conversation_id] = convo
            self._messages[conversation_id] = []
            return convo
        if existing.domain_id != domain_id or existing.role != role:
            raise ConversationScopeError(
                f"conversation {conversation_id!r} belongs to "
                f"(domain={existing.domain_id!r}, role={existing.role!r}), not "
                f"(domain={domain_id!r}, role={role!r})"
            )
        return existing

    def append_message(
        self,
        conversation_id: str,
        *,
        sender: str,
        content: str,
        grounded: bool | None = None,
        sources: list[str] | None = None,
        search_query: str | None = None,
    ) -> Message:
        if conversation_id not in self._conversations:
            raise ConversationError(f"no such conversation {conversation_id!r}; open it first")
        log = self._messages[conversation_id]
        msg = Message(
            conversation_id=conversation_id,
            turn_index=len(log),
            sender=sender,
            content=content,
            grounded=grounded,
            sources=list(sources or []),
            search_query=search_query,
        )
        log.append(msg)
        return msg

    def recent_exchanges(self, conversation_id: str, *, limit_turns: int) -> list[Exchange]:
        exchanges = _pair_exchanges(self._messages.get(conversation_id, []))
        return exchanges[-limit_turns:] if limit_turns else []

    def list_messages(self, conversation_id: str) -> list[Message]:
        return list(self._messages.get(conversation_id, []))


class PostgresConversationStore:
    """Postgres-backed store via psycopg 3. Plain SQL, no ORM (two tables).

    psycopg is imported lazily so importing this module never requires the driver; a store built
    without a reachable database only fails when a method actually touches it. Each call opens and
    commits its own connection — at chat cadence the connection cost is immaterial next to the LLM
    call, and it keeps the store stateless and leak-free.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def _connect(self) -> Any:
        import psycopg

        return psycopg.connect(self._dsn)

    def ensure_schema(self, schema_sql: str) -> None:
        """Create the tables if absent (idempotent). Run at startup, like the Qdrant collection."""
        with self._connect() as conn:
            conn.execute(schema_sql)

    def open_conversation(self, conversation_id: str, domain_id: str, role: str) -> Conversation:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO conversations (conversation_id, domain_id, role) "
                "VALUES (%s, %s, %s) ON CONFLICT (conversation_id) DO NOTHING",
                (conversation_id, domain_id, role),
            )
            row = conn.execute(
                "SELECT domain_id, role FROM conversations WHERE conversation_id = %s",
                (conversation_id,),
            ).fetchone()
        stored_domain, stored_role = row
        if stored_domain != domain_id or stored_role != role:
            raise ConversationScopeError(
                f"conversation {conversation_id!r} belongs to "
                f"(domain={stored_domain!r}, role={stored_role!r}), not "
                f"(domain={domain_id!r}, role={role!r})"
            )
        return Conversation(conversation_id, stored_domain, stored_role)

    def append_message(
        self,
        conversation_id: str,
        *,
        sender: str,
        content: str,
        grounded: bool | None = None,
        sources: list[str] | None = None,
        search_query: str | None = None,
    ) -> Message:
        from psycopg.types.json import Jsonb

        source_list = list(sources or [])
        with self._connect() as conn:
            next_index = conn.execute(
                "SELECT COALESCE(MAX(turn_index) + 1, 0) FROM messages WHERE conversation_id = %s",
                (conversation_id,),
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO messages "
                "(conversation_id, turn_index, sender, content, grounded, sources, search_query) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (conversation_id, next_index, sender, content, grounded, Jsonb(source_list),
                 search_query),
            )
            conn.execute(
                "UPDATE conversations SET updated_at = now() WHERE conversation_id = %s",
                (conversation_id,),
            )
        return Message(
            conversation_id=conversation_id, turn_index=next_index, sender=sender, content=content,
            grounded=grounded, sources=source_list, search_query=search_query,
        )

    def _fetch_messages(self, conversation_id: str) -> list[Message]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT conversation_id, turn_index, sender, content, grounded, sources, "
                "search_query FROM messages WHERE conversation_id = %s ORDER BY turn_index ASC",
                (conversation_id,),
            ).fetchall()
        return [
            Message(
                conversation_id=r[0], turn_index=r[1], sender=r[2], content=r[3],
                grounded=r[4], sources=list(r[5] or []), search_query=r[6],
            )
            for r in rows
        ]

    def recent_exchanges(self, conversation_id: str, *, limit_turns: int) -> list[Exchange]:
        exchanges = _pair_exchanges(self._fetch_messages(conversation_id))
        return exchanges[-limit_turns:] if limit_turns else []

    def list_messages(self, conversation_id: str) -> list[Message]:
        return self._fetch_messages(conversation_id)


def build_conversation_store(dsn: str | None = None) -> ConversationStore:
    """Build the Postgres store from ``dsn`` or ``CHATBOT_POSTGRES_DSN``; fail loud if unset.

    The DSN is infrastructure, read from the environment (decision 4) — not an experiment
    parameter, so it is deliberately absent from the config sections and their hash.
    """
    resolved = dsn or os.environ.get(_DSN_ENV)
    if not resolved:
        raise ConversationError(
            f"no Postgres DSN: set ${_DSN_ENV} (e.g. postgresql://chatbot@localhost:5432/chatbot)"
        )
    return PostgresConversationStore(resolved)
