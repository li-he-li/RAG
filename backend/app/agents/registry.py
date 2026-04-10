from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agents.base import AgentBase


class SkillNotFoundError(KeyError):
    pass


@dataclass(frozen=True, slots=True)
class SkillRegistryEntry:
    name: str
    agent_class: type[AgentBase[Any, Any]]
    metadata: dict[str, Any]


class SkillRegistry:
    def __init__(self) -> None:
        self._entries: dict[str, SkillRegistryEntry] = {}

    def register(
        self,
        name: str,
        agent_class: type[AgentBase[Any, Any]],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._entries[name] = SkillRegistryEntry(
            name=name,
            agent_class=agent_class,
            metadata=dict(metadata or {}),
        )

    def discover(self, name: str) -> SkillRegistryEntry:
        try:
            return self._entries[name]
        except KeyError as exc:
            raise SkillNotFoundError(name) from exc

    def list_capabilities(self) -> list[dict[str, Any]]:
        return [
            {"name": name, **entry.metadata}
            for name, entry in self._entries.items()
        ]
