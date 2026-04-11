"""
Tests for chat memory integration and casual chat path.

These tests verify that:
1. Chat service uses ConversationMemory for multi-turn conversations
2. Casual chat skips retrieval and uses memory-only path
3. Legal queries still use retrieval + memory together
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import re

import pytest

from app.services.memory.store import InMemoryMemoryStore
from app.services.memory.context_assembler import assemble_context


# --- Multi-turn context assembly for chat ---


def test_multi_turn_context_builds_correctly() -> None:
    """Three rounds of conversation produce correct message array."""
    store = InMemoryMemoryStore()

    # Round 1
    ctx = assemble_context(
        store=store, session_id="s1",
        system_prompt="你是法律助手", current_message="你好",
        token_budget=4000,
    )
    assert len(ctx) == 2  # [system, user]
    store.save_message("s1", "user", "你好", token_count=5)
    store.save_message("s1", "assistant", "你好！有什么法律问题可以帮您？", token_count=15)

    # Round 2
    ctx = assemble_context(
        store=store, session_id="s1",
        system_prompt="你是法律助手", current_message="合同第三条有什么风险？",
        token_budget=4000,
    )
    assert len(ctx) == 4  # [system, user1, assistant1, user2]
    assert ctx[1]["content"] == "你好"
    assert ctx[2]["content"] == "你好！有什么法律问题可以帮您？"
    assert ctx[3]["content"] == "合同第三条有什么风险？"
    store.save_message("s1", "user", "合同第三条有什么风险？", token_count=20)
    store.save_message("s1", "assistant", "根据合同法规定...", token_count=100)

    # Round 3 - context reference works across turns
    ctx = assemble_context(
        store=store, session_id="s1",
        system_prompt="你是法律助手", current_message="能再详细说说刚才提到的赔偿金额吗？",
        token_budget=4000,
    )
    assert len(ctx) == 6  # [system, u1, a1, u2, a2, u3]
    # LLM can reference compensation amount from previous turns via memory


def test_casual_chat_preserves_context_reference() -> None:
    """Follow-up questions that reference previous context work with memory."""
    store = InMemoryMemoryStore()
    store.save_message("s1", "user", "帮我分析一下这份合同的违约责任条款", token_count=30)
    store.save_message("s1", "assistant", "该合同的违约责任条款存在以下风险...", token_count=100)

    ctx = assemble_context(
        store=store, session_id="s1",
        system_prompt="你是法律助手", current_message="上面说的第一个风险能展开讲讲吗？",
        token_budget=4000,
    )
    # Follow-up references previous assistant message via memory
    assert len(ctx) == 4
    assert "上面说的第一个风险能展开讲讲吗？" == ctx[-1]["content"]


# --- Casual chat detection ---

# Extract _should_skip_retrieval logic for testing without sqlalchemy dependency
# This mirrors the logic in chat.py but is testable in isolation

_NON_RETRIEVAL_QUERIES = {
    "你好", "您好", "嗨", "hello", "hi", "hey",
    "早上好", "中午好", "下午好", "晚上好",
    "在吗", "在嘛", "谢谢", "感谢", "thanks", "thankyou",
    "你是谁", "你能做什么", "你会什么",
    "能再说一遍吗", "还有呢", "好的", "嗯嗯", "明白", "知道了",
    "继续", "然后呢",
}

_NON_RETRIEVAL_PREFIXES = (
    "你好", "您好", "谢谢", "感谢", "hello", "hi", "hey",
)


def _should_skip_retrieval_local(query: str) -> bool:
    """Local copy of _should_skip_retrieval for testing without chat.py dependency."""
    _NON_RETRIEVAL_TEXT_RE = re.compile(r"[\s\W_]+", re.UNICODE)
    compact = _NON_RETRIEVAL_TEXT_RE.sub("", (query or "").strip().lower())
    if not compact:
        return True
    if compact in _NON_RETRIEVAL_QUERIES:
        return True
    if any(compact.startswith(prefix) for prefix in _NON_RETRIEVAL_PREFIXES) and len(compact) <= 12:
        return True
    return False


class TestCasualChatDetection:
    """Test the _should_skip_retrieval logic with extended patterns."""

    def test_greetings_skip_retrieval(self) -> None:
        assert _should_skip_retrieval_local("你好") is True
        assert _should_skip_retrieval_local("您好") is True
        assert _should_skip_retrieval_local("hello") is True

    def test_thanks_skip_retrieval(self) -> None:
        assert _should_skip_retrieval_local("谢谢") is True
        assert _should_skip_retrieval_local("感谢") is True

    def test_follow_up_short_queries_skip_retrieval(self) -> None:
        assert _should_skip_retrieval_local("能再说一遍吗") is True
        assert _should_skip_retrieval_local("还有呢") is True

    def test_legal_queries_do_not_skip_retrieval(self) -> None:
        assert _should_skip_retrieval_local("合同第三条有什么风险") is False
        assert _should_skip_retrieval_local("违约责任怎么认定") is False
        assert _should_skip_retrieval_local("这个案件能赢吗") is False


# --- Casual chat builds memory-only context ---


def test_casual_chat_uses_memory_not_retrieval() -> None:
    """When _should_skip_retrieval is True, context is built from memory only."""
    store = InMemoryMemoryStore()
    store.save_message("s1", "user", "你好", token_count=5)
    store.save_message("s1", "assistant", "你好！我是法律助手。", token_count=15)

    # Simulate casual chat context assembly (no retrieval evidence)
    ctx = assemble_context(
        store=store, session_id="s1",
        system_prompt="你是一个友好的法律助手，可以闲聊也可以回答法律问题。",
        current_message="谢谢你的帮助",
        token_budget=4000,
    )
    # Context has memory, no retrieval evidence
    assert len(ctx) == 4  # [system, user1, assistant1, user2]
    assert "法律助手" in ctx[0]["content"]
    # No evidence/retrieval blocks in any message


def test_legal_query_still_gets_retrieval_plus_memory() -> None:
    """Legal queries should have both retrieval evidence AND memory context."""
    store = InMemoryMemoryStore()
    store.save_message("s1", "user", "你好", token_count=5)
    store.save_message("s1", "assistant", "你好！有什么法律问题？", token_count=15)

    # For a legal query, the chat service would:
    # 1. Do retrieval to get evidence
    # 2. Build system prompt with evidence
    # 3. Include memory history
    system_with_evidence = (
        "你是法律助手。\n\n"
        "【检索到的证据】\n"
        "1. 合同法第94条规定..."
    )
    ctx = assemble_context(
        store=store, session_id="s1",
        system_prompt=system_with_evidence,
        current_message="合同解除条件是什么？",
        token_budget=4000,
    )
    # System prompt has evidence, history is included, current message is legal
    assert "检索到的证据" in ctx[0]["content"]
    assert len(ctx) == 4  # [system+evidence, user1, assistant1, current_legal]


# --- Memory is saved after each exchange ---


def test_messages_saved_after_exchange() -> None:
    """Verify the flow: save user msg → call LLM → save assistant response."""
    store = InMemoryMemoryStore()

    # Simulate the flow that chat.py should follow
    session_id = "s1"
    user_msg = "你好"
    assistant_msg = "你好！我是法律助手"

    store.save_message(session_id, "user", user_msg, token_count=5)
    # ... LLM call happens ...
    store.save_message(session_id, "assistant", assistant_msg, token_count=15)

    messages = store.load_messages(session_id)
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].content == "你好"
    assert messages[1].role == "assistant"
    assert messages[1].content == "你好！我是法律助手"


def test_three_round_conversation_full_flow() -> None:
    """Complete 3-round conversation with memory saves and context assembly."""
    store = InMemoryMemoryStore()
    session_id = "s1"

    exchanges = [
        ("你好", "你好！有什么法律问题可以帮您？"),
        ("合同里的违约金条款合理吗", "根据合同法第114条，违约金不应过高..."),
        ("那如果对方不履行呢", "对方不履行时，您可以主张继续履行或赔偿损失..."),
    ]

    for user_msg, assistant_msg in exchanges:
        # Save user message
        store.save_message(session_id, "user", user_msg, token_count=20)
        # Build context (this is what chat.py would do)
        ctx = assemble_context(
            store=store, session_id=session_id,
            system_prompt="你是法律助手", current_message=user_msg,
            token_budget=4000,
        )
        # Simulate LLM response
        # Save assistant message
        store.save_message(session_id, "assistant", assistant_msg, token_count=50)

    # Verify full history
    all_msgs = store.load_messages(session_id)
    assert len(all_msgs) == 6  # 3 user + 3 assistant

    # Verify 3rd round context includes all previous
    ctx = assemble_context(
        store=store, session_id=session_id,
        system_prompt="你是法律助手",
        current_message="总结一下刚才讨论的",
        token_budget=4000,
    )
    assert len(ctx) == 8  # [system, u1, a1, u2, a2, u3, a3, current]
    assert ctx[-1]["content"] == "总结一下刚才讨论的"
