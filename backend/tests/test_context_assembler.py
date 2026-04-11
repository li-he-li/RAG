"""Tests for context assembler — token-budget-aware message array construction."""
from __future__ import annotations

from app.services.memory.context_assembler import (
    assemble_context,
    estimate_token_count,
)
from app.services.memory.store import InMemoryMemoryStore


def _make_store_with_history(
    *pairs: tuple[str, str],
    tokens_per_msg: int = 100,
) -> InMemoryMemoryStore:
    """Create a store with user/assistant message pairs."""
    store = InMemoryMemoryStore()
    for user_msg, assistant_msg in pairs:
        store.save_message("s1", "user", user_msg, token_count=tokens_per_msg)
        store.save_message("s1", "assistant", assistant_msg, token_count=tokens_per_msg)
    return store


# --- Token estimation ---


def test_estimate_token_count_non_empty() -> None:
    count = estimate_token_count("这是一段中文测试文本")
    assert count > 0


def test_estimate_token_count_empty() -> None:
    assert estimate_token_count("") == 0


def test_estimate_token_count_approximate() -> None:
    # Chinese text: roughly 1 token per 2 chars
    text = "你好世界" * 50  # 200 chars
    count = estimate_token_count(text)
    assert 50 < count < 200  # reasonable range


# --- assemble_context ---


def test_first_message_no_history() -> None:
    """First message in a new session produces [system, user]."""
    store = InMemoryMemoryStore()
    messages = assemble_context(
        store=store,
        session_id="s1",
        system_prompt="你是法律助手",
        current_message="你好",
        token_budget=4000,
    )
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "你好"


def test_multi_turn_with_history() -> None:
    """Messages include history between system and current message."""
    store = InMemoryMemoryStore()
    store.save_message("s1", "user", "第一条", token_count=50)
    store.save_message("s1", "assistant", "回复一", token_count=50)
    store.save_message("s1", "user", "第二条", token_count=50)
    store.save_message("s1", "assistant", "回复二", token_count=50)

    messages = assemble_context(
        store=store,
        session_id="s1",
        system_prompt="你是法律助手",
        current_message="第三条",
        token_budget=4000,
    )
    # [system, user1, assistant1, user2, assistant2, current_user]
    assert len(messages) == 6
    assert messages[0]["role"] == "system"
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"] == "第三条"
    assert messages[1]["content"] == "第一条"
    assert messages[2]["content"] == "回复一"


def test_history_truncated_by_token_budget() -> None:
    """Old messages are dropped when exceeding token budget."""
    store = InMemoryMemoryStore()
    # 5 rounds = 10 messages * 200 tokens = 2000 total
    for i in range(5):
        store.save_message("s1", "user", f"问题{i}", token_count=200)
        store.save_message("s1", "assistant", f"回答{i}", token_count=200)

    messages = assemble_context(
        store=store,
        session_id="s1",
        system_prompt="你是法律助手",
        current_message="新问题",
        token_budget=600,  # fits ~2 messages + system + current
    )
    # Should have: [system, recent_history..., current_user]
    # Budget 600: recent assistant(200) + recent user(200) + current + system
    assert len(messages) >= 3  # at least system + some history + current
    assert messages[0]["role"] == "system"
    assert messages[-1]["role"] == "user"


def test_compact_summary_injected_when_old_messages_dropped() -> None:
    """When old messages are dropped, a compact summary placeholder is included."""
    store = InMemoryMemoryStore()
    for i in range(10):
        store.save_message("s1", "user", f"长问题{i}关于合同条款的风险分析", token_count=300)
        store.save_message("s1", "assistant", f"长回答{i}根据相关法律规定...", token_count=300)

    messages = assemble_context(
        store=store,
        session_id="s1",
        system_prompt="你是法律助手",
        current_message="总结一下",
        token_budget=800,  # very tight, forces compact
    )
    # Should have compact_summary in metadata of system-like message
    # At minimum: system + current
    assert len(messages) >= 2
    # Check if any message has compact_summary metadata
    has_summary = any(
        msg.get("metadata", {}).get("type") == "compact_summary"
        or msg.get("role") == "system" and "之前的对话" in msg.get("content", "")
        for msg in messages
    )
    # If history was truncated, there should be a summary marker
    total_history_tokens = sum(
        300 for i in range(10) for _ in range(2)
    )  # 6000 tokens
    if total_history_tokens > 800:
        assert has_summary, "Expected compact summary when history exceeds budget"


def test_system_prompt_always_first() -> None:
    """System prompt is always the first message."""
    store = InMemoryMemoryStore()
    store.save_message("s1", "user", "hi", token_count=10)

    messages = assemble_context(
        store=store,
        session_id="s1",
        system_prompt="系统指令",
        current_message="新消息",
        token_budget=4000,
    )
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "系统指令"


def test_current_message_always_last() -> None:
    """Current user message is always the last message."""
    store = InMemoryMemoryStore()
    store.save_message("s1", "user", "history", token_count=10)

    messages = assemble_context(
        store=store,
        session_id="s1",
        system_prompt="系统",
        current_message="我的问题",
        token_budget=4000,
    )
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"] == "我的问题"
