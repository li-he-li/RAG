"""
Conversation memory store.

Provides both an in-memory implementation (for testing/development)
and a protocol for PostgreSQL-backed production implementation.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ConversationMessage:
    id: str
    session_id: str
    role: str  # system / user / assistant / tool
    content: str
    token_count: int
    created_at: datetime
    metadata: dict[str, object] = field(default_factory=dict)


@runtime_checkable
class MemoryStore(Protocol):
    """Protocol for conversation memory storage backends."""

    def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        token_count: int = 0,
        metadata: dict[str, object] | None = None,
    ) -> ConversationMessage: ...

    def load_messages(
        self,
        session_id: str,
        *,
        limit: int | None = None,
        token_budget: int | None = None,
    ) -> list[ConversationMessage]: ...

    def delete_session(self, session_id: str) -> None: ...

    def cleanup_old_sessions(self, *, max_age_hours: int = 24) -> int: ...

    def get_session_token_total(self, session_id: str) -> int: ...


class InMemoryMemoryStore:
    """In-memory implementation of MemoryStore for testing and development."""

    def __init__(self) -> None:
        self._messages: dict[str, list[ConversationMessage]] = {}

    def save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        token_count: int = 0,
        metadata: dict[str, object] | None = None,
    ) -> ConversationMessage:
        msg = ConversationMessage(
            id=str(uuid.uuid4()),
            session_id=session_id,
            role=role,
            content=content,
            token_count=token_count,
            created_at=datetime.now(timezone.utc),
            metadata=metadata or {},
        )
        self._messages.setdefault(session_id, []).append(msg)
        return msg

    def load_messages(
        self,
        session_id: str,
        *,
        limit: int | None = None,
        token_budget: int | None = None,
    ) -> list[ConversationMessage]:
        all_msgs = list(self._messages.get(session_id, []))
        if not all_msgs:
            return []

        # Apply limit first (take last N)
        if limit is not None:
            all_msgs = all_msgs[-limit:]

        # Apply token budget (from most recent backwards)
        if token_budget is not None:
            selected: list[ConversationMessage] = []
            total = 0
            for msg in reversed(all_msgs):
                if total + msg.token_count > token_budget:
                    break
                selected.insert(0, msg)
                total += msg.token_count
            return selected

        return all_msgs

    def delete_session(self, session_id: str) -> None:
        self._messages.pop(session_id, None)

    def cleanup_old_sessions(self, *, max_age_hours: int = 24) -> int:
        cutoff = datetime.now(timezone.utc) - __import__("datetime").timedelta(hours=max_age_hours)
        deleted = 0
        sessions_to_delete: list[str] = []
        for session_id, messages in self._messages.items():
            if messages and messages[-1].created_at < cutoff:
                sessions_to_delete.append(session_id)
        for session_id in sessions_to_delete:
            del self._messages[session_id]
            deleted += 1
        return deleted

    def get_session_token_total(self, session_id: str) -> int:
        messages = self._messages.get(session_id, [])
        return sum(m.token_count for m in messages)
