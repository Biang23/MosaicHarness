from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ContextBudget:
    """Deterministic, tokenizer-independent context budget."""

    max_chars: int = 100_000
    reserve_chars: int = 10_000
    keep_recent_messages: int = 20

    def __post_init__(self) -> None:
        if self.max_chars <= 0:
            raise ValueError("max_chars must be positive")
        if self.reserve_chars < 0 or self.reserve_chars >= self.max_chars:
            raise ValueError("reserve_chars must be between 0 and max_chars")
        if self.keep_recent_messages < 1:
            raise ValueError("keep_recent_messages must be positive")

    @property
    def usable_chars(self) -> int:
        return self.max_chars - self.reserve_chars


@dataclass(frozen=True, slots=True)
class ContextSelection:
    messages: tuple[Any, ...]
    estimated_chars: int
    estimated_tokens: int
    dropped_messages: int
    truncated: bool


class ContextManager:
    """Select a bounded message window while preserving system and recent context."""

    def __init__(self, budget: ContextBudget | None = None) -> None:
        self.budget = budget or ContextBudget()

    def select(self, messages: Sequence[Any]) -> ContextSelection:
        source = tuple(messages)
        total_chars = sum(_message_chars(message) for message in source)
        if total_chars <= self.budget.usable_chars:
            return _selection(source, total_chars, dropped=0, truncated=False)

        system = tuple(message for message in source if _message_type(message) == "system")
        recent = tuple(source[-self.budget.keep_recent_messages :])
        selected: list[Any] = []
        seen: set[int] = set()
        for message in (*system, *recent):
            identity = id(message)
            if identity not in seen:
                selected.append(message)
                seen.add(identity)
        selected.sort(key=lambda item: source.index(item))
        selected_chars = sum(_message_chars(message) for message in selected)
        while selected and selected_chars > self.budget.usable_chars:
            removable = next(
                (index for index, item in enumerate(selected) if _message_type(item) != "system"),
                None,
            )
            if removable is None:
                break
            selected_chars -= _message_chars(selected.pop(removable))
        return _selection(
            tuple(selected),
            selected_chars,
            dropped=len(source) - len(selected),
            truncated=selected_chars < total_chars,
        )


def _selection(
    messages: tuple[Any, ...],
    estimated_chars: int,
    *,
    dropped: int,
    truncated: bool,
) -> ContextSelection:
    return ContextSelection(
        messages=messages,
        estimated_chars=estimated_chars,
        estimated_tokens=max(1, (estimated_chars + 3) // 4) if estimated_chars else 0,
        dropped_messages=dropped,
        truncated=truncated,
    )


def _message_type(message: Any) -> str:
    return str(getattr(message, "type", ""))


def _message_chars(message: Any) -> int:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return len(content)
    return len(str(content))
