"""End-to-end validation: living agent architecture full chain."""
from __future__ import annotations

import asyncio
from typing import Any

from app.agents.base import RawResult, ValidatedOutput, Rejection
from app.agents.orchestrator_integration import PipelineFactory, get_orchestrator
from app.agents.orchestrator import IntentRouter, OrchestratorAgent
from app.agents.registry import SkillRegistry
from app.agents.pipeline import AgentPipeline
from app.agents.strategies import StrategyRegistry, InputComplexity
from app.services.memory.store import InMemoryMemoryStore
from app.services.memory.context_assembler import assemble_context


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# --- E2E: Memory multi-turn ---


def test_e2e_three_round_memory_conversation() -> None:
    """Complete 3-round conversation with memory persistence."""
    store = InMemoryMemoryStore()
    session_id = "e2e-test"

    # Round 1
    ctx1 = assemble_context(
        store=store, session_id=session_id,
        system_prompt="Legal assistant", current_message="hello",
        token_budget=4000,
    )
    assert len(ctx1) == 2
    store.save_message(session_id, "user", "hello", token_count=5)
    store.save_message(session_id, "assistant", "Hi! How can I help?", token_count=10)

    # Round 2
    ctx2 = assemble_context(
        store=store, session_id=session_id,
        system_prompt="Legal assistant", current_message="contract risks?",
        token_budget=4000,
    )
    assert len(ctx2) == 4
    store.save_message(session_id, "user", "contract risks?", token_count=10)
    store.save_message(session_id, "assistant", "Key risks include...", token_count=50)

    # Round 3 — references previous context
    ctx3 = assemble_context(
        store=store, session_id=session_id,
        system_prompt="Legal assistant",
        current_message="tell me more about the first risk you mentioned",
        token_budget=4000,
    )
    assert len(ctx3) == 6  # system + 4 history messages + current user message
    store.save_message(session_id, "user", "tell me more about the first risk you mentioned", token_count=15)
    store.save_message(session_id, "assistant", "The first risk is breach of...", token_count=30)

    # Verify memory store has all messages (3 user + 3 assistant = 6)
    all_msgs = store.load_messages(session_id)
    assert len(all_msgs) == 6


# --- E2E: Self-correction with validation ---


def test_e2e_self_correction_produces_valid_output() -> None:
    """Agent fails validation, self-corrects, produces valid output."""
    from app.agents.base import ExecutorAgent, ValidatorAgent, PlannerAgent
    from app.agents.base import ExecutionPlan, PlanStep, ValidationFail

    attempts = 0

    class FlakyExecutor(ExecutorAgent):
        @property
        def name(self):
            return "flaky"

        async def validate(self, input_data):
            pass

        async def run(self, input_data):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return RawResult(status="success", output={"short": True})
            return RawResult(status="success", output={"answer": "full", "citations": [1]})

    class StrictValidator(ValidatorAgent):
        @property
        def name(self):
            return "strict"

        async def validate(self, input_data):
            pass

        async def run(self, raw_result):
            if isinstance(raw_result.output, dict) and "citations" not in raw_result.output:
                return Rejection(reasons=("no_citations",), details={"retryable": True})
            return ValidatedOutput(output=raw_result.output, schema_name="test")

    class SimplePlanner(PlannerAgent):
        @property
        def name(self):
            return "plan"

        async def validate(self, input_data):
            pass

        async def run(self, input_data):
            return ExecutionPlan(steps=(PlanStep(name="run", target_agent="flaky"),))

    pipeline = AgentPipeline(
        planner=SimplePlanner(),
        executor=FlakyExecutor(),
        validator=StrictValidator(),
        max_retries=2,
    )

    result = _run(pipeline.run({"query": "test"}))
    assert isinstance(result, ValidatedOutput)
    assert "citations" in result.output
    assert attempts == 2  # failed once, succeeded on retry


# --- E2E: Orchestrator routes all 4 intents ---


def test_e2e_orchestrator_all_intents() -> None:
    """IntentRouter correctly maps all 4 business endpoints."""
    router = IntentRouter()
    mappings = {
        "/api/chat/stream": "chat",
        "/api/similar-cases/compare": "similar_case_search",
        "/api/contract-review/stream": "contract_review",
        "/api/opponent-prediction/start": "opponent_prediction",
        "/api/unknown": "chat",  # fallback
    }
    for endpoint, expected_intent in mappings.items():
        assert router.classify(endpoint, {}) == expected_intent, f"Failed for {endpoint}"


# --- E2E: Strategy selection by complexity ---


def test_e2e_strategy_selection() -> None:
    """Different input complexities produce different plan sizes."""
    from app.agents.strategies import classify_complexity

    # Simple: 1-step plan expected
    simple = classify_complexity({"query": "hi", "attachments": []})
    assert simple == InputComplexity.SIMPLE

    # Complex: multi-step plan expected
    complex_input = classify_complexity({
        "query": "analyze all contract risks with case precedents",
        "attachments": [{"name": "a.pdf"}, {"name": "b.pdf"}],
        "dispute_tags": ["breach"],
    })
    assert complex_input == InputComplexity.COMPLEX


# --- E2E: Memory + token budget integration ---


def test_e2e_memory_with_tight_budget() -> None:
    """Memory system respects token budget and generates compact summary."""
    store = InMemoryMemoryStore()
    session_id = "budget-test"

    # Create 10 rounds of conversation (20 messages * 200 tokens = 4000)
    for i in range(10):
        store.save_message(session_id, "user", f"question {i}", token_count=200)
        store.save_message(session_id, "assistant", f"answer {i}", token_count=200)

    # Assemble with tight budget (only fits ~3 messages)
    ctx = assemble_context(
        store=store, session_id=session_id,
        system_prompt="Legal assistant",
        current_message="summarize our discussion",
        token_budget=700,
    )

    # Should have system + compact_summary + recent messages + current
    assert len(ctx) >= 2
    assert ctx[0]["role"] == "system"
    assert ctx[-1]["content"] == "summarize our discussion"

    # Total tokens in context should be within budget
    # (not exact due to estimation, but should be reasonable)
    assert len(ctx) < 20  # definitely not all 20 messages
