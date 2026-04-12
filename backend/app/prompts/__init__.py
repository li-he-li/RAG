from pathlib import Path

from app.prompts.registry import (
    PromptNotFoundError,
    PromptRegistry,
    PromptSegment,
    PromptTemplate,
    PromptVariableError,
    RenderedPrompt,
)
from app.prompts.signatures import build_domain_signatures, build_dspy_signature

__all__ = [
    "PromptNotFoundError",
    "PromptRegistry",
    "PromptSegment",
    "PromptTemplate",
    "PromptVariableError",
    "RenderedPrompt",
    "build_domain_signatures",
    "build_dspy_signature",
]

# Global singleton — shared across admin optimization, agents, and services
_registry: PromptRegistry | None = None


def get_prompt_registry() -> PromptRegistry:
    """Get or create the global PromptRegistry singleton."""
    global _registry
    if _registry is None:
        prompt_dir = Path(__file__).parent
        _registry = PromptRegistry(prompt_dir)
    return _registry
