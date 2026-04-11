from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.prompts.registry import PromptRegistry, PromptTemplate


@dataclass(frozen=True, slots=True)
class OutputSpec:
    field_name: str
    description: str


_OUTPUT_SPECS: dict[str, OutputSpec] = {
    "similar_case_search": OutputSpec(
        field_name="comparison_markdown",
        description="Structured similar-case comparison in markdown.",
    ),
    "contract_review": OutputSpec(
        field_name="review_markdown",
        description="Markdown contract review result.",
    ),
    "opponent_prediction": OutputSpec(
        field_name="prediction_report",
        description="Predicted opponent strategy report.",
    ),
    "chat": OutputSpec(
        field_name="answer",
        description="Grounded chat answer with citations.",
    ),
    "retrieval_explanation": OutputSpec(
        field_name="explanation",
        description="Explanation of retrieval and evidence ranking.",
    ),
}


def load_dspy(dspy_module: Any | None = None) -> Any:
    if dspy_module is not None:
        return dspy_module
    try:
        import dspy  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised in runtime, not unit tests
        raise RuntimeError(
            "DSPy integration requires the optional dependency 'dspy-ai>=2.5'."
        ) from exc
    return dspy


def _class_name_for_prompt(prompt_name: str) -> str:
    return "".join(part.capitalize() for part in prompt_name.split("_")) + "Signature"


def get_output_spec(prompt_name: str) -> OutputSpec:
    return _OUTPUT_SPECS.get(
        prompt_name,
        OutputSpec(field_name="answer", description=f"Optimized output for {prompt_name}."),
    )


def build_dspy_signature(
    template: PromptTemplate,
    *,
    dspy_module: Any | None = None,
) -> type:
    dspy = load_dspy(dspy_module)
    output_spec = get_output_spec(template.name)

    attrs: dict[str, Any] = {
        "__doc__": f"DSPy signature for prompt template '{template.name}'.",
        "__prompt_name__": template.name,
        "__prompt_version__": template.version,
        "__input_fields__": {},
        "__output_fields__": {},
    }

    for variable in template.variables:
        attrs[variable] = dspy.InputField(desc=f"Prompt variable: {variable}")
        attrs["__input_fields__"][variable] = attrs[variable]

    attrs[output_spec.field_name] = dspy.OutputField(desc=output_spec.description)
    attrs["__output_fields__"][output_spec.field_name] = attrs[output_spec.field_name]

    return type(_class_name_for_prompt(template.name), (dspy.Signature,), attrs)


def build_domain_signatures(
    registry: PromptRegistry,
    *,
    dspy_module: Any | None = None,
) -> dict[str, type]:
    return {
        name: build_dspy_signature(template, dspy_module=dspy_module)
        for name, template in registry._templates.items()
    }
