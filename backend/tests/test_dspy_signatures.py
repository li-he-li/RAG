from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import shutil
import uuid

import pytest

from app.prompts.registry import PromptRegistry, PromptSegment, PromptTemplate
from app.services.trajectory.logger import TrajectoryLogger


def _write_prompt(prompt_dir: Path, *, name: str = "contract_review") -> None:
    prompt_dir.mkdir(parents=True, exist_ok=True)
    (prompt_dir / f"{name}.yaml").write_text(
        "\n".join(
            [
                f"name: {name}",
                'version: "1.0.0"',
                "variables:",
                "  - file_name",
                "  - template_name",
                "segments:",
                "  - role: system",
                "    content: You are a review assistant.",
                "  - role: user",
                "    content: |-\n      File={{file_name}}\n      Template={{template_name}}",
            ]
        ),
        encoding="utf-8",
    )


class _FakeField:
    def __init__(self, *, desc: str = "") -> None:
        self.desc = desc


class _FakeSignature:
    pass


class _FakePrediction(dict):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.__dict__.update(kwargs)


class _FakePredict:
    def __init__(self, signature: type) -> None:
        self.signature = signature
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> _FakePrediction:
        self.calls.append(kwargs)
        output_names = tuple(getattr(self.signature, "__output_fields__", {"answer": None}).keys())
        payload = {name: f"predicted:{kwargs.get('file_name', 'unknown')}" for name in output_names}
        return _FakePrediction(**payload)


class _FakeModule:
    pass


class _FakeExample:
    def __init__(self, **kwargs: Any) -> None:
        self.data = dict(kwargs)
        self.input_keys: tuple[str, ...] = ()

    def with_inputs(self, *keys: str) -> "_FakeExample":
        self.input_keys = tuple(keys)
        return self


class _FakeBootstrapFewShot:
    def __init__(self, metric: Any = None, **config: Any) -> None:
        self.metric = metric
        self.config = config
        self.compile_calls: list[dict[str, Any]] = []

    def compile(self, student: Any, *, teacher: Any = None, trainset: list[Any]) -> Any:
        self.compile_calls.append(
            {
                "student": student,
                "teacher": teacher,
                "trainset": trainset,
            }
        )
        student._compiled = True
        return student


@dataclass
class _FakeDSPy:
    Signature: type = _FakeSignature
    Module: type = _FakeModule
    Predict: type = _FakePredict
    Example: type = _FakeExample
    BootstrapFewShot: type = _FakeBootstrapFewShot

    @staticmethod
    def InputField(*, desc: str = "") -> _FakeField:
        return _FakeField(desc=desc)

    @staticmethod
    def OutputField(*, desc: str = "") -> _FakeField:
        return _FakeField(desc=desc)

    @staticmethod
    def Prediction(**kwargs: Any) -> _FakePrediction:
        return _FakePrediction(**kwargs)


@pytest.fixture
def fake_dspy() -> _FakeDSPy:
    return _FakeDSPy()


@pytest.fixture
def prompt_registry() -> PromptRegistry:
    prompt_dir = Path("test-workspace") / "dspy-signatures" / uuid.uuid4().hex
    prompt_dir.mkdir(parents=True, exist_ok=False)
    _write_prompt(prompt_dir, name="contract_review")
    _write_prompt(prompt_dir, name="chat")
    try:
        yield PromptRegistry(prompt_dir)
    finally:
        shutil.rmtree(prompt_dir, ignore_errors=True)


class TestDSPySignatures:
    def test_registry_builds_dynamic_signature_from_prompt_template(
        self,
        prompt_registry: PromptRegistry,
        fake_dspy: _FakeDSPy,
    ) -> None:
        signature = prompt_registry.to_dspy_signature("contract_review", dspy_module=fake_dspy)

        assert signature.__name__ == "ContractReviewSignature"
        assert issubclass(signature, fake_dspy.Signature)
        assert tuple(signature.__input_fields__.keys()) == ("file_name", "template_name")
        assert tuple(signature.__output_fields__.keys()) == ("review_markdown",)

    def test_build_all_domain_signatures(
        self,
        prompt_registry: PromptRegistry,
        fake_dspy: _FakeDSPy,
    ) -> None:
        from app.prompts.signatures import build_domain_signatures

        signatures = build_domain_signatures(prompt_registry, dspy_module=fake_dspy)

        assert set(signatures) == {"contract_review", "chat"}
        assert signatures["chat"].__name__ == "ChatSignature"


class TestPromptOptimizationModule:
    def test_module_wraps_registry_prompt_and_predictor(
        self,
        prompt_registry: PromptRegistry,
        fake_dspy: _FakeDSPy,
    ) -> None:
        from app.prompts.optimization import create_prompt_optimization_module

        module = create_prompt_optimization_module(
            prompt_registry,
            "contract_review",
            dspy_module=fake_dspy,
        )
        prediction = module.forward(file_name="A.docx", template_name="T1")

        assert prediction.review_markdown == "predicted:A.docx"
        assert module.prompt_name == "contract_review"
        assert module.rendered_prompt.name == "contract_review"
        assert module.predictor.calls == [{"file_name": "A.docx", "template_name": "T1"}]


class TestTrajectoryEvalset:
    def test_export_evalset_from_trajectory_records(
        self,
        fake_dspy: _FakeDSPy,
    ) -> None:
        from app.prompts.optimization import export_trajectory_evalset

        logger = TrajectoryLogger(session_id="sess-dspy")
        logger.record(
            agent_name="contract_review_executor",
            step_type="execute",
            input_data={"file_name": "A.docx", "template_name": "T1"},
            output={"review_markdown": "predicted:A.docx"},
            duration_ms=15.0,
            prompt_versions={"contract_review": "1.0.0"},
        )

        examples = export_trajectory_evalset(
            records=logger.records,
            prompt_name="contract_review",
            input_keys=("file_name", "template_name"),
            output_key="review_markdown",
            dspy_module=fake_dspy,
        )

        assert len(examples) == 1
        assert examples[0].data["file_name"] == "A.docx"
        assert examples[0].data["review_markdown"] == "predicted:A.docx"
        assert examples[0].input_keys == ("file_name", "template_name")

    def test_export_evalset_skips_records_without_input_payload(
        self,
        fake_dspy: _FakeDSPy,
    ) -> None:
        from app.prompts.optimization import export_trajectory_evalset

        records = [
            {
                "session_id": "sess-1",
                "agent_name": "contract_review_executor",
                "step_type": "execute",
                "input_hash": "abc",
                "output": {"review_markdown": "x"},
                "prompt_versions": {"contract_review": "1.0.0"},
            }
        ]

        examples = export_trajectory_evalset(
            records=records,
            prompt_name="contract_review",
            input_keys=("file_name", "template_name"),
            output_key="review_markdown",
            dspy_module=fake_dspy,
        )

        assert examples == []


class TestOptimizerAndFallback:
    def test_optimizer_compiles_module_and_validates_on_evalset(
        self,
        prompt_registry: PromptRegistry,
        fake_dspy: _FakeDSPy,
    ) -> None:
        from app.prompts.optimization import (
            create_bootstrap_optimizer,
            create_exact_match_metric,
            create_prompt_optimization_module,
            optimize_prompt_module,
        )

        module = create_prompt_optimization_module(
            prompt_registry,
            "contract_review",
            dspy_module=fake_dspy,
        )
        optimizer = create_bootstrap_optimizer(
            dspy_module=fake_dspy,
            metric=create_exact_match_metric("review_markdown"),
            max_bootstrapped_demos=2,
            max_labeled_demos=1,
        )
        evalset = [
            fake_dspy.Example(
                file_name="A.docx",
                template_name="T1",
                review_markdown="predicted:A.docx",
            ).with_inputs("file_name", "template_name")
        ]

        result = optimize_prompt_module(
            module=module,
            optimizer=optimizer,
            trainset=evalset,
            evalset=evalset,
            metric=create_exact_match_metric("review_markdown"),
        )

        assert result.validation_score == 1.0
        assert result.compiled is True
        assert optimizer.compile_calls[0]["trainset"] == evalset

    def test_manual_few_shot_fallback_creates_ab_variants(
        self,
        prompt_registry: PromptRegistry,
    ) -> None:
        from app.prompts.optimization import build_ab_test_variants

        examples = [
            {
                "inputs": {"file_name": "A.docx", "template_name": "T1"},
                "output": "predicted:A.docx",
            }
        ]

        baseline, candidate = build_ab_test_variants(
            prompt_registry,
            "contract_review",
            examples=examples,
        )

        assert baseline.version == "1.0.0"
        assert candidate.version == "1.0.0-fewshot-a"
        assert candidate.name == "contract_review"
        assert len(candidate.segments) > len(baseline.segments)
        assert any(segment.role == "assistant" for segment in candidate.segments)
