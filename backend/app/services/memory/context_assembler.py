"""
Context assembler — builds the messages array for LLM calls.

Loads conversation history from MemoryStore within token budget,
generates compact summaries for truncated old messages, and
assembles the final [system, (summary), ...history, current] array.
"""
from __future__ import annotations

import re

from app.services.memory.store import MemoryStore


def estimate_token_count(text: str) -> int:
    """Estimate token count for a text string.

    Simple heuristic:
    - Chinese characters: ~1 token per 2 characters
    - English words: ~1 token per 0.75 words
    - Mixed: conservative estimate
    """
    if not text:
        return 0
    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    other_chars = len(text) - chinese_chars
    other_words = len(re.findall(r"[a-zA-Z]+", text))
    # Chinese: ~0.5 token per char, English: ~1.3 tokens per word
    return max(1, int(chinese_chars * 0.5 + other_words * 1.3 + other_chars * 0.2))


def assemble_context(
    *,
    store: MemoryStore,
    session_id: str,
    system_prompt: str,
    current_message: str,
    token_budget: int,
) -> list[dict[str, str]]:
    """Assemble the messages array for an LLM call.

    Returns: [system_prompt, (compact_summary), ...history, current_message]
    The total token count of history + current stays within token_budget.
    """
    messages: list[dict[str, str]] = []

    # 1. System prompt always first
    system_tokens = estimate_token_count(system_prompt)
    messages.append({"role": "system", "content": system_prompt})

    # 2. Load history within remaining budget
    current_tokens = estimate_token_count(current_message)
    history_budget = token_budget - system_tokens - current_tokens
    history_budget = max(0, history_budget)

    history = store.load_messages(session_id, token_budget=history_budget)
    total_history_tokens = store.get_session_token_total(session_id)
    all_history = store.load_messages(session_id)

    # 3. Check if truncation happened — inject compact summary if so
    if len(history) < len(all_history) and len(all_history) > 0:
        # Generate a placeholder compact summary
        # (In production, this would call LLM to summarize)
        summary = (
            "【之前的对话摘要】用户之前就该案件进行了多轮法律咨询，"
            "讨论了合同条款风险、相关法律规定和可能的应对策略。"
        )
        messages.append({
            "role": "system",
            "content": summary,
            "metadata": {"type": "compact_summary"},
        })

    # 4. Add history messages
    for msg in history:
        messages.append({"role": msg.role, "content": msg.content})

    # 5. Current message always last
    messages.append({"role": "user", "content": current_message})

    return messages
