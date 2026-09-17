from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


def _csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class ToolsConfig:
    enabled: bool = False
    include_metadata_in_prompt: bool = True


@dataclass(frozen=True, slots=True)
class MemoryConfig:
    enabled: bool = False
    auto_recall: bool = False
    auto_write: bool = False
    top_k: int = 5


@dataclass(frozen=True, slots=True)
class SkillsConfig:
    enabled: bool = False
    roots: tuple[str, ...] = ()
    progressive_disclosure: bool = True


@dataclass(frozen=True, slots=True)
class CompactionConfig:
    enabled: bool = False
    model: Any | None = None
    trigger_tokens: int = 32_000
    keep_messages: int = 20
    clear_old_tool_results: bool = True


@dataclass(frozen=True, slots=True)
class ObservabilityConfig:
    enabled: bool = False
    provider: str = "langsmith"
    project_name: str | None = None
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MosaicConfig:
    """Global defaults for capability activation.

    A capability is active only when it is listed in enabled_capabilities and
    its own config has enabled=True. Agents can override the list explicitly.
    """

    enabled_capabilities: tuple[str, ...] = ()
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    skills: SkillsConfig = field(default_factory=SkillsConfig)
    compaction: CompactionConfig = field(default_factory=CompactionConfig)
    observability: ObservabilityConfig = field(default_factory=ObservabilityConfig)

    @classmethod
    def from_env(cls) -> MosaicConfig:
        """Load safe, built-in capability aliases from MOSAIC_* variables."""
        requested = list(_csv(os.getenv("MOSAIC_CAPABILITIES")))
        for name, variable in (
            ("tools", "MOSAIC_TOOLS_ENABLED"),
            ("memory", "MOSAIC_MEMORY_ENABLED"),
            ("skills", "MOSAIC_SKILLS_ENABLED"),
            ("compaction", "MOSAIC_COMPACTION_ENABLED"),
            ("observability", "MOSAIC_LANGSMITH_ENABLED"),
        ):
            if _bool(os.getenv(variable)) and name not in requested:
                requested.append(name)
        capabilities = tuple(requested)
        return cls(
            enabled_capabilities=capabilities,
            tools=ToolsConfig(
                enabled="tools" in capabilities or _bool(os.getenv("MOSAIC_TOOLS_ENABLED"))
            ),
            memory=MemoryConfig(
                enabled="memory" in capabilities or _bool(os.getenv("MOSAIC_MEMORY_ENABLED")),
                auto_recall=_bool(os.getenv("MOSAIC_MEMORY_AUTO_RECALL")),
                auto_write=_bool(os.getenv("MOSAIC_MEMORY_AUTO_WRITE")),
                top_k=int(os.getenv("MOSAIC_MEMORY_TOP_K", "5")),
            ),
            skills=SkillsConfig(
                enabled="skills" in capabilities or _bool(os.getenv("MOSAIC_SKILLS_ENABLED")),
                roots=_csv(os.getenv("MOSAIC_SKILL_PATHS")),
            ),
            compaction=CompactionConfig(
                enabled="compaction" in capabilities
                or _bool(os.getenv("MOSAIC_COMPACTION_ENABLED")),
                trigger_tokens=int(os.getenv("MOSAIC_COMPACTION_TRIGGER_TOKENS", "32000")),
                keep_messages=int(os.getenv("MOSAIC_COMPACTION_KEEP_MESSAGES", "20")),
            ),
            observability=ObservabilityConfig(
                enabled="observability" in capabilities
                or _bool(os.getenv("MOSAIC_LANGSMITH_ENABLED")),
                provider=os.getenv("MOSAIC_OBSERVABILITY_PROVIDER", "langsmith"),
                project_name=os.getenv("MOSAIC_LANGSMITH_PROJECT"),
                tags=_csv(os.getenv("MOSAIC_LANGSMITH_TAGS")),
            ),
        )
