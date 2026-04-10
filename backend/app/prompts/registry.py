from __future__ import annotations

import logging
import re
import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Thread
from typing import Any

import yaml
from watchfiles import watch

logger = logging.getLogger(__name__)

_PLACEHOLDER_RE = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")
_pinned_templates: ContextVar[dict[str, "PromptTemplate"] | None] = ContextVar(
    "prompt_registry_pinned_templates",
    default=None,
)


class PromptNotFoundError(KeyError):
    pass


class PromptVariableError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PromptSegment:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    name: str
    version: str
    segments: tuple[PromptSegment, ...]
    variables: tuple[str, ...]
    source_path: Path


@dataclass(frozen=True, slots=True)
class RenderedPrompt:
    name: str
    version: str
    segments: tuple[PromptSegment, ...]
    token_budget: dict[str, int] | None = None

    def as_messages(self) -> list[dict[str, str]]:
        return [{"role": segment.role, "content": segment.content} for segment in self.segments]


class PromptRegistry:
    def __init__(self, prompt_dir: str | Path) -> None:
        self.prompt_dir = Path(prompt_dir)
        self._templates: dict[str, PromptTemplate] = {}
        self._file_versions: dict[Path, dict[str, str]] = {}
        self._file_mtimes: dict[Path, int] = {}
        self._file_signatures: dict[Path, str] = {}
        self._watch_stop = Event()
        self._watch_thread: Thread | None = None
        self.reload()

    def reload(self) -> None:
        previous_versions = {
            name: template.version for name, template in self._templates.items()
        }
        templates: dict[str, PromptTemplate] = {}
        file_versions: dict[Path, dict[str, str]] = {}
        file_mtimes: dict[Path, int] = {}
        file_signatures: dict[Path, str] = {}

        if not self.prompt_dir.exists():
            logger.info("Prompt directory does not exist: %s", self.prompt_dir)
            self._templates = {}
            self._file_versions = {}
            self._file_mtimes = {}
            self._file_signatures = {}
            return

        for path in self._prompt_files():
            try:
                parsed_templates = self._load_prompt_file(path)
            except Exception as exc:
                logger.warning("Skipping invalid prompt file %s: %s", path, exc)
                continue

            file_versions[path] = {}
            for template in parsed_templates:
                previous = previous_versions.get(template.name)
                if previous and previous != template.version:
                    logger.info(
                        "Prompt %s version changed from %s to %s",
                        template.name,
                        previous,
                        template.version,
                    )
                elif previous == template.version and template.name in self._templates:
                    old_template = self._templates[template.name]
                    if old_template.segments != template.segments:
                        logger.warning(
                            "Prompt %s content changed without version bump %s",
                            template.name,
                            template.version,
                        )
                templates[template.name] = template
                file_versions[path][template.name] = template.version

            try:
                file_mtimes[path] = path.stat().st_mtime_ns
                file_signatures[path] = self._file_signature(path)
            except FileNotFoundError:
                continue

        if not templates:
            logger.info("No prompt templates loaded from %s", self.prompt_dir)

        self._templates = templates
        self._file_versions = file_versions
        self._file_mtimes = file_mtimes
        self._file_signatures = file_signatures

    def reload_changed_files(self) -> None:
        current_files = set(self._prompt_files()) if self.prompt_dir.exists() else set()
        known_files = set(self._file_mtimes)
        changed = current_files != known_files
        if not changed:
            for path in current_files:
                try:
                    if (
                        path.stat().st_mtime_ns != self._file_mtimes.get(path)
                        or self._file_signature(path) != self._file_signatures.get(path)
                    ):
                        changed = True
                        break
                except FileNotFoundError:
                    changed = True
                    break
        if changed:
            self.reload()

    def start_hot_reload(self) -> None:
        if self._watch_thread and self._watch_thread.is_alive():
            return
        self._watch_stop.clear()
        self._watch_thread = Thread(target=self._watch_loop, daemon=True)
        self._watch_thread.start()

    def stop_hot_reload(self) -> None:
        self._watch_stop.set()
        if self._watch_thread:
            self._watch_thread.join(timeout=1.0)

    def get_template(self, name: str) -> PromptTemplate:
        pinned = _pinned_templates.get()
        if pinned is not None and name in pinned:
            return pinned[name]
        try:
            template = self._templates[name]
        except KeyError as exc:
            raise PromptNotFoundError(name) from exc
        if pinned is not None:
            pinned[name] = template
        return template

    def get_version(self, name: str) -> str:
        return self.get_template(name).version

    def render(self, name: str, variables: dict[str, Any] | None = None) -> RenderedPrompt:
        template = self.get_template(name)
        values = dict(variables or {})
        missing = [variable for variable in template.variables if variable not in values]
        if missing:
            raise PromptVariableError(
                f"Missing prompt variable(s) for {name}: {', '.join(missing)}"
            )

        rendered_segments = tuple(
            PromptSegment(
                role=segment.role,
                content=self._render_content(segment.content, values),
            )
            for segment in template.segments
        )
        return RenderedPrompt(
            name=template.name,
            version=template.version,
            segments=rendered_segments,
        )

    def render_with_budget(
        self,
        name: str,
        variables: dict[str, Any] | None = None,
        *,
        token_budget_manager: Any,
        context_window: int,
        generation_tokens: int,
        model: str = "deepseek-chat",
    ) -> RenderedPrompt:
        rendered = self.render(name, variables)
        token_budget = token_budget_manager.enforce_messages_budget(
            rendered.as_messages(),
            generation_tokens=generation_tokens,
            context_window=context_window,
            model=model,
        )
        return RenderedPrompt(
            name=rendered.name,
            version=rendered.version,
            segments=rendered.segments,
            token_budget=token_budget,
        )

    @contextmanager
    def request_context(self) -> Iterator[dict[str, str]]:
        pinned: dict[str, PromptTemplate] = {}
        token: Token[dict[str, PromptTemplate] | None] = _pinned_templates.set(pinned)
        try:
            yield self.get_pinned_versions()
        finally:
            _pinned_templates.reset(token)

    def get_pinned_versions(self) -> dict[str, str]:
        pinned = _pinned_templates.get() or {}
        return {name: template.version for name, template in pinned.items()}

    def to_dspy_signature(self, name: str) -> type:
        self.get_template(name)
        raise NotImplementedError("DSPy integration is deferred to Phase 4.")

    def _watch_loop(self) -> None:
        if not self.prompt_dir.exists():
            return
        for _changes in watch(
            self.prompt_dir,
            stop_event=self._watch_stop,
            watch_filter=lambda _, path: path.endswith((".yaml", ".yml")),
        ):
            self.reload()

    def _prompt_files(self) -> list[Path]:
        return sorted(
            path
            for path in self.prompt_dir.iterdir()
            if path.is_file() and path.suffix.lower() in {".yaml", ".yml"}
        )

    def _load_prompt_file(self, path: Path) -> list[PromptTemplate]:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if raw is None:
            return []
        if not isinstance(raw, dict):
            raise ValueError("prompt file must contain a mapping")
        entries = raw.get("templates") or [raw]
        if not isinstance(entries, list):
            raise ValueError("templates must be a list")
        return [self._parse_template(entry, path) for entry in entries]

    def _file_signature(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _parse_template(self, data: Any, path: Path) -> PromptTemplate:
        if not isinstance(data, dict):
            raise ValueError("template must be a mapping")
        name = data.get("name")
        version = data.get("version")
        variables = data.get("variables")
        segments = data.get("segments")
        if not isinstance(name, str) or not name:
            raise ValueError("template is missing required field: name")
        if not isinstance(version, str) or not version:
            raise ValueError(f"template {name} is missing required field: version")
        if not isinstance(variables, list) or not all(
            isinstance(item, str) for item in variables
        ):
            raise ValueError(f"template {name} field variables must be a string list")
        if not isinstance(segments, list) or not segments:
            raise ValueError(f"template {name} is missing required field: segments")

        parsed_segments = []
        for segment in segments:
            if not isinstance(segment, dict):
                raise ValueError(f"template {name} segment must be a mapping")
            role = segment.get("role")
            content = segment.get("content")
            if role not in {"system", "user", "assistant"}:
                raise ValueError(f"template {name} segment has invalid role: {role}")
            if not isinstance(content, str):
                raise ValueError(f"template {name} segment content must be a string")
            parsed_segments.append(PromptSegment(role=role, content=content))

        return PromptTemplate(
            name=name,
            version=version,
            segments=tuple(parsed_segments),
            variables=tuple(variables),
            source_path=path,
        )

    def _render_content(self, content: str, values: dict[str, Any]) -> str:
        def _replace(match: re.Match[str]) -> str:
            variable = match.group(1)
            if variable not in values:
                raise PromptVariableError(f"Missing prompt variable: {variable}")
            return str(values[variable])

        return _PLACEHOLDER_RE.sub(_replace, content)
