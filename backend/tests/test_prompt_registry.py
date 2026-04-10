from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest

from app.prompts.registry import (
    PromptNotFoundError,
    PromptRegistry,
    PromptVariableError,
)


@pytest.fixture
def prompt_dir() -> Path:
    root = Path("test-workspace") / "prompt-registry" / uuid.uuid4().hex
    root.mkdir(parents=True, exist_ok=False)
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _write_prompt(
    prompt_dir: Path,
    *,
    name: str = "contract_review",
    version: str = "1.0.0",
    content: str = "Review {{case_name}} for {{party_a}} vs {{party_b}}.",
) -> Path:
    path = prompt_dir / f"{name}.yaml"
    path.write_text(
        "\n".join(
            [
                f"name: {name}",
                f"version: {version}",
                "variables:",
                "  - case_name",
                "  - party_a",
                "  - party_b",
                "segments:",
                "  - role: system",
                "    content: You are a legal assistant.",
                "  - role: user",
                f"    content: {content!r}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_registry_loads_yaml_and_renders_variables(prompt_dir: Path) -> None:
    _write_prompt(prompt_dir)
    registry = PromptRegistry(prompt_dir)

    template = registry.get_template("contract_review")
    rendered = registry.render(
        "contract_review",
        {
            "case_name": "lease dispute",
            "party_a": "Alice",
            "party_b": "Bob",
            "ignored": "unused",
        },
    )

    assert template.name == "contract_review"
    assert template.version == "1.0.0"
    assert registry.get_version("contract_review") == "1.0.0"
    assert [segment.role for segment in rendered.segments] == ["system", "user"]
    assert rendered.segments[1].content == "Review lease dispute for Alice vs Bob."


def test_registry_rejects_missing_required_variables(prompt_dir: Path) -> None:
    _write_prompt(prompt_dir)
    registry = PromptRegistry(prompt_dir)

    with pytest.raises(PromptVariableError) as error:
        registry.render("contract_review", {"case_name": "lease dispute"})

    assert "party_a" in str(error.value)


def test_registry_skips_invalid_yaml_without_crashing(prompt_dir: Path) -> None:
    _write_prompt(prompt_dir, name="valid_prompt")
    (prompt_dir / "invalid.yaml").write_text("name: invalid\nsegments:\n", encoding="utf-8")
    registry = PromptRegistry(prompt_dir)

    assert registry.get_template("valid_prompt").name == "valid_prompt"
    with pytest.raises(PromptNotFoundError):
        registry.get_template("invalid")


def test_request_scoped_version_pinning_survives_reload(prompt_dir: Path) -> None:
    prompt_path = _write_prompt(prompt_dir, version="1.0.0", content="Version one {{case_name}}.")
    registry = PromptRegistry(prompt_dir)

    with registry.request_context():
        first = registry.render(
            "contract_review",
            {"case_name": "case", "party_a": "A", "party_b": "B"},
        )
        prompt_path.write_text(
            prompt_path.read_text(encoding="utf-8").replace("1.0.0", "1.1.0").replace(
                "Version one",
                "Version two",
            ),
            encoding="utf-8",
        )
        registry.reload()
        pinned = registry.render(
            "contract_review",
            {"case_name": "case", "party_a": "A", "party_b": "B"},
        )
        snapshot = registry.get_pinned_versions()

    current = registry.render(
        "contract_review",
        {"case_name": "case", "party_a": "A", "party_b": "B"},
    )

    assert first.version == "1.0.0"
    assert pinned.version == "1.0.0"
    assert pinned.segments[1].content == "Version one case."
    assert snapshot == {"contract_review": "1.0.0"}
    assert current.version == "1.1.0"
    assert current.segments[1].content == "Version two case."


def test_hot_reload_refreshes_modified_and_deleted_files(prompt_dir: Path) -> None:
    prompt_path = _write_prompt(prompt_dir, version="1.0.0", content="Old {{case_name}}.")
    registry = PromptRegistry(prompt_dir)

    prompt_path.write_text(
        prompt_path.read_text(encoding="utf-8").replace("1.0.0", "1.1.0").replace(
            "Old",
            "New",
        ),
        encoding="utf-8",
    )
    registry.reload_changed_files()
    rendered = registry.render(
        "contract_review",
        {"case_name": "case", "party_a": "A", "party_b": "B"},
    )

    assert rendered.version == "1.1.0"
    assert rendered.segments[1].content == "New case."

    prompt_path.unlink()
    registry.reload_changed_files()

    with pytest.raises(PromptNotFoundError):
        registry.get_template("contract_review")


def test_dspy_signature_is_deferred_to_phase_four(prompt_dir: Path) -> None:
    _write_prompt(prompt_dir)
    registry = PromptRegistry(prompt_dir)

    with pytest.raises(NotImplementedError, match="Phase 4"):
        registry.to_dspy_signature("contract_review")


def test_default_prompt_directory_loads_business_templates() -> None:
    prompt_dir = Path("app") / "prompts"
    registry = PromptRegistry(prompt_dir)

    for prompt_name in [
        "similar_case_search",
        "contract_review",
        "opponent_case_profile",
        "opponent_prediction",
        "chat_grounded",
        "retrieval_explanation",
    ]:
        assert registry.get_version(prompt_name) == "1.0.0"
