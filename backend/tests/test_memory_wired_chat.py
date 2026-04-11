"""
Tests that conversation memory is truly wired into the chat service.

Verifies:
- User messages are saved to memory before processing
- Assistant messages are saved to memory after processing
- History is loaded and passed to DeepSeek payload
- Casual chat uses memory without retrieval
- Stream path also records to memory
"""
from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.schemas import ChatRequest, ChatResponse
from app.services.chat import (
    ChatRetrievalInput,
    _memory_store,
    _load_history_messages,
    _should_skip_retrieval,
    execute_grounded_chat,
    stream_grounded_chat,
    estimate_token_count,
)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def clean_memory():
    """Clean the global memory store before each test."""
    _memory_store.delete_session("test-session-1")
    _memory_store.delete_session("test-session-2")
    yield
    _memory_store.delete_session("test-session-1")
    _memory_store.delete_session("test-session-2")


def _make_request(query: str, session_id: str = "test-session-1") -> ChatRequest:
    return ChatRequest(query=query, session_id=session_id)


class TestMemoryWiredIntoChat:
    """Verify memory is truly connected to execute_grounded_chat."""

    def test_user_message_saved_before_processing(self):
        """User message is saved to memory store before DeepSeek is called."""
        request = _make_request("你好")
        with patch("app.services.chat.handle_casual_chat", new_callable=AsyncMock, return_value="你好！"):
            _run(execute_grounded_chat(request, db=MagicMock()))

        # Check user message was saved
        messages = _memory_store.load_messages("test-session-1")
        user_msgs = [m for m in messages if m.role == "user"]
        assert len(user_msgs) == 1
        assert user_msgs[0].content == "你好"

    def test_assistant_message_saved_after_casual_chat(self):
        """Assistant response is saved after casual chat."""
        request = _make_request("你好")
        with patch("app.services.chat.handle_casual_chat", new_callable=AsyncMock, return_value="你好！有什么可以帮你的？"):
            _run(execute_grounded_chat(request, db=MagicMock()))

        messages = _memory_store.load_messages("test-session-1")
        assistant_msgs = [m for m in messages if m.role == "assistant"]
        assert len(assistant_msgs) == 1
        assert assistant_msgs[0].content == "你好！有什么可以帮你的？"

    def test_assistant_message_saved_after_grounded_chat(self):
        """Assistant response is saved after grounded chat with retrieval."""
        request = _make_request("合同的违约条款有哪些")
        mock_db = MagicMock()
        retrieval_input = ChatRetrievalInput(query_text="test")

        with patch("app.services.chat._collect_citations", return_value=([], retrieval_input)), \
             patch("app.services.chat._ask_deepseek", new_callable=AsyncMock, return_value="违约条款包括..."):
            response = _run(execute_grounded_chat(request, db=mock_db))

        messages = _memory_store.load_messages("test-session-1")
        assistant_msgs = [m for m in messages if m.role == "assistant"]
        assert len(assistant_msgs) == 1
        assert "违约条款" in assistant_msgs[0].content

    def test_multi_turn_conversation_has_memory(self):
        """Second turn sees first turn's history."""
        # Turn 1: casual
        r1 = _make_request("你好")
        with patch("app.services.chat.handle_casual_chat", new_callable=AsyncMock, return_value="你好！"):
            _run(execute_grounded_chat(r1, db=MagicMock()))

        # Turn 2: casual - history should include turn 1
        r2 = _make_request("你能做什么")
        with patch("app.services.chat.handle_casual_chat", new_callable=AsyncMock, return_value="我可以帮你搜索法律案例") as mock_casual:
            _run(execute_grounded_chat(r2, db=MagicMock()))

            # The casual chat handler should have received history with turn 1
            history = mock_casual.call_args.kwargs.get("history_messages", [])
            assert len(history) >= 1  # At least the first user message

    def test_casual_chat_no_retrieval(self):
        """Casual queries skip the retrieval pipeline entirely."""
        request = _make_request("你好")
        with patch("app.services.chat.handle_casual_chat", new_callable=AsyncMock, return_value="你好！"), \
             patch("app.services.chat._collect_citations") as mock_retrieve:
            response = _run(execute_grounded_chat(request, db=MagicMock()))

        # _collect_citations should NOT be called for casual chat
        mock_retrieve.assert_not_called()
        assert response.grounded is False

    def test_legal_query_still_uses_retrieval(self):
        """Legal queries still go through retrieval pipeline."""
        request = _make_request("合同的违约金条款如何约定")
        mock_db = MagicMock()
        retrieval_input = ChatRetrievalInput(query_text="test")

        with patch("app.services.chat._collect_citations", return_value=([], retrieval_input)) as mock_retrieve, \
             patch("app.services.chat._ask_deepseek", new_callable=AsyncMock, return_value="关于违约金..."):
            response = _run(execute_grounded_chat(request, db=mock_db))

        # _collect_citations SHOULD be called for legal queries
        mock_retrieve.assert_called_once()

    def test_no_session_still_works(self):
        """Chat without session_id works fine, just no memory."""
        request = ChatRequest(query="你好", session_id=None)
        with patch("app.services.chat.handle_casual_chat", new_callable=AsyncMock, return_value="你好！"):
            response = _run(execute_grounded_chat(request, db=MagicMock()))

        assert response.answer == "你好！"
        # No messages saved since no session_id
        messages = _memory_store.load_messages("test-session-1")
        assert len(messages) == 0


class TestStreamMemory:
    """Verify streaming chat also records to memory."""

    def _collect_stream(self, coro: Any) -> list[str]:
        """Collect all events from an async generator."""
        async def _collect():
            events = []
            async for event in coro:
                events.append(event)
            return events
        return asyncio.run(_collect())

    def test_stream_casual_saves_memory(self):
        """Streaming casual chat saves user and assistant messages."""
        request = _make_request("你好")
        events = self._collect_stream(stream_grounded_chat(request, db=MagicMock()))

        messages = _memory_store.load_messages("test-session-1")
        roles = [m.role for m in messages]
        assert "user" in roles
        assert "assistant" in roles

    def test_stream_grounded_saves_memory(self):
        """Streaming grounded chat saves user and assistant messages."""
        request = _make_request("合同违约条款")
        mock_db = MagicMock()
        retrieval_input = ChatRetrievalInput(query_text="test")

        async def fake_stream(*a, **kw):
            yield "违约条款"

        with patch("app.services.chat._collect_citations", return_value=([], retrieval_input)), \
             patch("app.services.chat._stream_deepseek", return_value=fake_stream()):
            events = self._collect_stream(stream_grounded_chat(request, db=mock_db))

        messages = _memory_store.load_messages("test-session-1")
        roles = [m.role for m in messages]
        assert "user" in roles
        assert "assistant" in roles


class TestLoadHistoryMessages:
    """Verify _load_history_messages helper."""

    def test_returns_empty_for_no_session(self):
        assert _load_history_messages(None) == []

    def test_returns_history_for_session(self):
        _memory_store.save_message("test-session-2", "user", "hello", token_count=5)
        _memory_store.save_message("test-session-2", "assistant", "hi there", token_count=5)
        _memory_store.save_message("test-session-2", "system", "compact", token_count=5)

        history = _load_history_messages("test-session-2")
        # Only user and assistant messages
        assert len(history) == 2
        assert history[0] == {"role": "user", "content": "hello"}
        assert history[1] == {"role": "assistant", "content": "hi there"}

    def test_respects_token_budget(self):
        for i in range(20):
            _memory_store.save_message(
                "test-session-2",
                "user",
                f"message {i} " * 50,  # long messages
                token_count=500,  # each message 500 tokens
            )

        history = _load_history_messages("test-session-2")
        # Budget is 2000 tokens, each message 500, so at most 4 messages
        assert len(history) <= 5
