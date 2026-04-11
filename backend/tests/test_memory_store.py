"""Tests for ConversationMessage model and MemoryStore."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from app.services.memory.store import (
    ConversationMessage,
    InMemoryMemoryStore,
    MemoryStore,
)


# --- ConversationMessage dataclass ---


def test_conversation_message_creation() -> None:
    msg = ConversationMessage(
        id="msg1",
        session_id="sess1",
        role="user",
        content="Hello",
        token_count=5,
        created_at=datetime.now(timezone.utc),
        metadata={},
    )
    assert msg.session_id == "sess1"
    assert msg.role == "user"
    assert msg.content == "Hello"
    assert msg.token_count == 5


# --- InMemoryMemoryStore (no DB dependency) ---


@pytest.fixture
def store() -> InMemoryMemoryStore:
    return InMemoryMemoryStore()


def test_save_and_load_single_message(store: InMemoryMemoryStore) -> None:
    store.save_message(
        session_id="s1",
        role="user",
        content="你好",
        token_count=10,
    )
    messages = store.load_messages("s1")
    assert len(messages) == 1
    assert messages[0].role == "user"
    assert messages[0].content == "你好"


def test_save_and_load_multiple_messages_ordered(store: InMemoryMemoryStore) -> None:
    store.save_message("s1", "user", "第一条", token_count=5)
    store.save_message("s1", "assistant", "回复一", token_count=8)
    store.save_message("s1", "user", "第二条", token_count=5)

    messages = store.load_messages("s1")
    assert len(messages) == 3
    assert messages[0].content == "第一条"
    assert messages[1].content == "回复一"
    assert messages[2].content == "第二条"


def test_different_sessions_isolated(store: InMemoryMemoryStore) -> None:
    store.save_message("s1", "user", "session 1 msg")
    store.save_message("s2", "user", "session 2 msg")

    assert len(store.load_messages("s1")) == 1
    assert len(store.load_messages("s2")) == 1
    assert store.load_messages("s1")[0].content == "session 1 msg"


def test_load_messages_with_limit(store: InMemoryMemoryStore) -> None:
    for i in range(10):
        store.save_message("s1", "user", f"msg {i}", token_count=5)

    messages = store.load_messages("s1", limit=3)
    assert len(messages) == 3
    # Should return the LAST 3 messages (most recent)
    assert messages[0].content == "msg 7"
    assert messages[1].content == "msg 8"
    assert messages[2].content == "msg 9"


def test_load_messages_with_token_budget(store: InMemoryMemoryStore) -> None:
    """Load messages within a token budget, keeping most recent."""
    store.save_message("s1", "user", "old", token_count=100)
    store.save_message("s1", "assistant", "old reply", token_count=100)
    store.save_message("s1", "user", "recent", token_count=50)
    store.save_message("s1", "assistant", "recent reply", token_count=50)

    messages = store.load_messages("s1", token_budget=120)
    # Should fit: recent(50) + recent reply(50) = 100 <= 120
    # old(100) would exceed, so skipped
    total = sum(m.token_count for m in messages)
    assert total <= 120
    assert len(messages) == 2
    assert messages[0].content == "recent"


def test_load_messages_empty_session(store: InMemoryMemoryStore) -> None:
    messages = store.load_messages("nonexistent")
    assert messages == []


def test_delete_session(store: InMemoryMemoryStore) -> None:
    store.save_message("s1", "user", "to delete")
    store.save_message("s2", "user", "keep this")

    store.delete_session("s1")

    assert store.load_messages("s1") == []
    assert len(store.load_messages("s2")) == 1


def test_cleanup_old_sessions(store: InMemoryMemoryStore) -> None:
    # Save a message and artificially age it
    old_msg = store.save_message("old_session", "user", "old", token_count=5)
    # Manually set created_at to 25 hours ago
    store._messages["old_session"][0] = ConversationMessage(
        id=old_msg.id,
        session_id="old_session",
        role="user",
        content="old",
        token_count=5,
        created_at=datetime.now(timezone.utc) - timedelta(hours=25),
        metadata={},
    )

    # Save a recent message
    store.save_message("new_session", "user", "new", token_count=5)

    deleted = store.cleanup_old_sessions(max_age_hours=24)
    assert deleted == 1
    assert store.load_messages("old_session") == []
    assert len(store.load_messages("new_session")) == 1


def test_save_message_returns_message_with_metadata(store: InMemoryMemoryStore) -> None:
    msg = store.save_message(
        "s1", "system", "summary",
        token_count=20,
        metadata={"type": "compact_summary"},
    )
    assert msg.metadata == {"type": "compact_summary"}


def test_get_session_token_total(store: InMemoryMemoryStore) -> None:
    store.save_message("s1", "user", "a", token_count=10)
    store.save_message("s1", "assistant", "b", token_count=20)
    store.save_message("s1", "user", "c", token_count=30)

    total = store.get_session_token_total("s1")
    assert total == 60


def test_get_session_token_total_empty(store: InMemoryMemoryStore) -> None:
    assert store.get_session_token_total("nonexistent") == 0
