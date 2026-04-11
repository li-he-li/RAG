from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from app.prompts.registry import PromptRegistry, PromptSegment, PromptTemplate
from app.prompts.signatures import get_output_spec, load_dspy


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    compiled_program: Any
    validation_score: float
    compiled: bool


def _coerce_field(source: Any, key: str) -> Any:
    if isinstance(source, dict):
        return source.get(key)
    if hasattr(source, "data") and isinstance(source.data, dict):
        return source.data.get(key)
    return getattr(source, key, None)


def _example_inputs(example: Any) -> dict[str, Any]:
    keys = tuple(getattr(example, "input_keys", ()))
    if hasattr(example, "data") and isinstance(example.data, dict):
        return {key: example.data[key] for key in keys if key in example.data}
    if isinstance(example, dict):
        return {key: example[key] for key in keys if key in example}
    return {key: getattr(example, key) for key in keys if hasattr(example, key)}


def create_prompt_optimization_module(
    registry: PromptRegistry,
    prompt_name: str,
    *,
    dspy_module: Any | None = None,
    predictor_factory: Any | None = None,
) -> Any:
    dspy = load_dspy(dspy_module)
    signature_cls = registry.to_dspy_signature(prompt_name, dspy_module=dspy)
    predictor = predictor_factory(signature_cls) if predictor_factory else dspy.Predict(signature_cls)

    class PromptOptimizationModule(dspy.Module):
        def __init__(self) -> None:
            self.prompt_name = prompt_name
            self.signature_cls = signature_cls
            self.predictor = predictor
            self.rendered_prompt = None

        def forward(self, **kwargs: Any) -> Any:
            self.rendered_prompt = registry.render(prompt_name, kwargs)
            return self.predictor(**kwargs)

    return PromptOptimizationModule()


def export_trajectory_evalset(
    *,
    records: Iterable[dict[str, Any]],
    prompt_name: str,
    input_keys: tuple[str, ...],
    output_key: str,
    dspy_module: Any | None = None,
) -> list[Any]:
    dspy = load_dspy(dspy_module)
    examples: list[Any] = []

    for record in records:
        prompt_versions = record.get("prompt_versions") or {}
        if prompt_name not in prompt_versions:
            continue

        input_payload = record.get("input_payload")
        output_payload = record.get("output")
        if not isinstance(input_payload, dict) or not isinstance(output_payload, dict):
            continue
        if output_key not in output_payload:
            continue

        example_data = {key: input_payload[key] for key in input_keys if key in input_payload}
        if len(example_data) != len(input_keys):
            continue
        example_data[output_key] = output_payload[output_key]
        examples.append(dspy.Example(**example_data).with_inputs(*input_keys))

    return examples


def create_exact_match_metric(output_key: str) -> Any:
    def metric(example: Any, prediction: Any, trace: Any = None) -> bool:  # noqa: ARG001
        return _coerce_field(example, output_key) == _coerce_field(prediction, output_key)

    return metric


def create_bootstrap_optimizer(
    *,
    dspy_module: Any | None = None,
    metric: Any,
    max_bootstrapped_demos: int = 4,
    max_labeled_demos: int = 4,
) -> Any:
    dspy = load_dspy(dspy_module)
    return dspy.BootstrapFewShot(
        metric=metric,
        max_bootstrapped_demos=max_bootstrapped_demos,
        max_labeled_demos=max_labeled_demos,
    )


def optimize_prompt_module(
    *,
    module: Any,
    optimizer: Any,
    trainset: list[Any],
    evalset: list[Any],
    metric: Any,
) -> OptimizationResult:
    compiled = optimizer.compile(module, trainset=trainset)
    passed = 0
    for example in evalset:
        prediction = compiled.forward(**_example_inputs(example))
        if metric(example, prediction):
            passed += 1
    score = passed / len(evalset) if evalset else 0.0
    return OptimizationResult(
        compiled_program=compiled,
        validation_score=score,
        compiled=bool(getattr(compiled, "_compiled", False)),
    )


def build_manual_few_shot_variant(
    registry: PromptRegistry,
    prompt_name: str,
    *,
    examples: list[dict[str, Any]],
    variant_suffix: str = "fewshot-a",
) -> PromptTemplate:
    baseline = registry.get_template(prompt_name)
    system_segments = tuple(segment for segment in baseline.segments if segment.role == "system")
    trailing_segments = tuple(segment for segment in baseline.segments if segment.role != "system")

    demo_segments: list[PromptSegment] = []
    for example in examples:
        inputs = dict(example.get("inputs") or {})
        output = str(example.get("output", ""))
        rendered = registry.render(prompt_name, inputs)
        demo_segments.extend(segment for segment in rendered.segments if segment.role == "user")
        demo_segments.append(PromptSegment(role="assistant", content=output))

    return PromptTemplate(
        name=baseline.name,
        version=f"{baseline.version}-{variant_suffix}",
        segments=system_segments + tuple(demo_segments) + trailing_segments,
        variables=baseline.variables,
        source_path=baseline.source_path,
    )


def build_ab_test_variants(
    registry: PromptRegistry,
    prompt_name: str,
    *,
    examples: list[dict[str, Any]],
) -> tuple[PromptTemplate, PromptTemplate]:
    baseline = registry.get_template(prompt_name)
    candidate = build_manual_few_shot_variant(
        registry,
        prompt_name,
        examples=examples,
        variant_suffix="fewshot-a",
    )
    return baseline, candidate


def output_key_for_prompt(prompt_name: str) -> str:
    return get_output_spec(prompt_name).field_name
