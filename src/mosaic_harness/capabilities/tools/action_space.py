from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ...config import ActionSpaceConfig
from .registry import ToolRegistry

_TOKEN = re.compile(r"[a-z0-9_]+")


@dataclass(frozen=True, slots=True)
class ToolSelection:
    selected: tuple[str, ...]
    candidates: tuple[str, ...]
    query: str
    reason: str


def select_tools(
    registry: ToolRegistry,
    *,
    requested: tuple[str, ...],
    config: ActionSpaceConfig,
    metadata: dict[str, Any],
) -> ToolSelection:
    candidates = tuple(dict.fromkeys((*registry.builtin_names, *requested)))
    if config.enabled:
        candidates = tuple(registry.names)
    allowed = _names(metadata.get("allowed_tool_names"))
    denied = _names(metadata.get("denied_tool_names"))
    if allowed:
        candidates = tuple(name for name in candidates if name in allowed)
    candidates = tuple(name for name in candidates if name not in denied)
    missing_requested = tuple(name for name in requested if name not in candidates)
    if missing_requested:
        raise ValueError(
            "agent tool_names are blocked by the action-space policy: "
            + ", ".join(missing_requested)
        )

    query = str(metadata.get("tool_query", "")).strip()
    if not config.enabled:
        return ToolSelection(candidates, candidates, query, "action space disabled")

    explicit = tuple(name for name in requested if name in candidates)
    remaining = tuple(name for name in candidates if name not in explicit)
    ranked = tuple(sorted(remaining, key=lambda name: _score(registry, name, query), reverse=True))
    if query:
        ranked = tuple(name for name in ranked if _score(registry, name, query) > 0)
    selected = tuple(dict.fromkeys((*explicit, *ranked[: config.max_tools])))
    return ToolSelection(
        selected,
        candidates,
        query,
        "ranked by tool_query" if query else "bounded",
    )


def _score(registry: ToolRegistry, name: str, query: str) -> int:
    if not query:
        return 0
    tool = registry.resolve((name,))[0]
    haystack = f"{tool.name} {tool.description}".casefold()
    return sum(1 for token in _TOKEN.findall(query.casefold()) if token in haystack)


def _names(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, (list, tuple, set)):
        return {str(item) for item in value}
    return set()
