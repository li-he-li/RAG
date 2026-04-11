from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Generic, Protocol, TypeVar, runtime_checkable

if TYPE_CHECKING:
    from app.agents.tool_governance import ToolGovernancePolicy

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


class ValidationError(ValueError):
    pass


# --- Validation Rule Protocol ---


@runtime_checkable
class ValidationRule(Protocol):
    """Protocol for pluggable validation rules used by ValidatorAgent."""

    @abstractmethod
    def check(self, output: Any) -> ValidationPass | ValidationFail:
        ...


class ValidationPass:
    """Indicates validation passed."""

    __slots__ = ("passed",)
    passed: bool

    def __init__(self) -> None:
        self.passed = True

    def __bool__(self) -> bool:
        return True


class ValidationFail:
    """Indicates validation failed with reason and retryability."""

    __slots__ = ("reason", "retryable", "passed")
    reason: str
    retryable: bool
    passed: bool

    def __init__(self, reason: str, *, retryable: bool = True) -> None:
        self.reason = reason
        self.retryable = retryable
        self.passed = False

    def __bool__(self) -> bool:
        return False


# --- Plan Data Structures ---


@dataclass(frozen=True, slots=True)
class PlanStep:
    name: str
    target_agent: str
    input_mapping: dict[str, Any] = field(default_factory=dict)
    expected_output_type: str = "object"
    condition: str | None = None
    parallel_group: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    steps: tuple[PlanStep, ...]


@dataclass(frozen=True, slots=True)
class RawResult:
    status: str
    output: Any
    intermediate_steps: list[dict[str, Any]] = field(default_factory=list)
    failed_step_index: int | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ValidatedOutput:
    output: Any
    schema_name: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Rejection:
    reasons: tuple[str, ...]
    details: dict[str, Any] = field(default_factory=dict)


class AgentBase(Generic[InputT, OutputT]):
    def __init__(self, *, tool_governance_policy: "ToolGovernancePolicy | None" = None) -> None:
        self.tool_governance_policy = tool_governance_policy

    @property
    def name(self) -> str:
        raise NotImplementedError

    async def validate(self, input_data: InputT) -> None:
        raise NotImplementedError

    async def run(self, input_data: InputT) -> OutputT:
        raise NotImplementedError

    async def execute(self, input_data: InputT) -> OutputT:
        await self.validate(input_data)
        return await self.run(input_data)

    async def can_handle(self, input_data: Any) -> float:
        """Return confidence score [0.0, 1.0] that this agent can handle the input.

        Default returns 0.0 — subclasses override to declare capabilities.
        Score >= 0.5 means the agent is a candidate.
        """
        return 0.0

    async def invoke_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        tool_governance_policy = getattr(self, "tool_governance_policy", None)
        if tool_governance_policy is None:
            from app.agents.tool_governance import ToolGovernancePolicy

            tool_governance_policy = ToolGovernancePolicy()
            self.tool_governance_policy = tool_governance_policy
        return await tool_governance_policy.invoke(
            agent_name=self.name,
            tool_name=tool_name,
            arguments=arguments,
        )


class PlannerAgent(AgentBase[InputT, OutputT]):
    pass


class ExecutorAgent(AgentBase[InputT, OutputT]):
    pass


class ValidatorAgent(AgentBase[InputT, OutputT]):
    pass
