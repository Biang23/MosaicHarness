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
class ActionSpaceConfig:
    enabled: bool = False
    max_tools: int = 12


@dataclass(frozen=True, slots=True)
class NetworkConfig:
    enabled: bool = False
    provider: str = "ddgs"
    timeout_seconds: float = 10.0
    max_response_bytes: int = 2_000_000
    allowed_domains: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FilesystemConfig:
    enabled: bool = False
    roots: tuple[str, ...] = ()
    max_read_bytes: int = 1_000_000


@dataclass(frozen=True, slots=True)
class DocumentsConfig:
    enabled: bool = False
    max_pages: int = 50
    max_output_chars: int = 200_000


@dataclass(frozen=True, slots=True)
class BuiltinsConfig:
    tools_enabled: bool = True
    skills_enabled: bool = True


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

    enabled_capabilities: tuple[str, ...] = ("tools", "skills")
    tools: ToolsConfig = field(default_factory=lambda: ToolsConfig(enabled=True))
    action_space: ActionSpaceConfig = field(default_factory=ActionSpaceConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    filesystem: FilesystemConfig = field(default_factory=FilesystemConfig)
    documents: DocumentsConfig = field(default_factory=DocumentsConfig)
    builtins: BuiltinsConfig = field(default_factory=BuiltinsConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    skills: SkillsConfig = field(default_factory=lambda: SkillsConfig(enabled=True))
    compaction: CompactionConfig = field(default_factory=CompactionConfig)
    observability: ObservabilityConfig = field(default_factory=ObservabilityConfig)

    @classmethod
    def from_env(cls) -> MosaicConfig:
        """Load safe, built-in capability aliases from MOSAIC_* variables."""
        requested = list(_csv(os.getenv("MOSAIC_CAPABILITIES")))
        if not requested:
            requested.extend(("tools", "skills"))
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
            action_space=ActionSpaceConfig(
                enabled=_bool(os.getenv("MOSAIC_ACTION_SPACE_ENABLED")),
                max_tools=int(os.getenv("MOSAIC_ACTION_SPACE_MAX_TOOLS", "12")),
            ),
            network=NetworkConfig(
                enabled=_bool(os.getenv("MOSAIC_NETWORK_ENABLED")),
                provider=os.getenv("MOSAIC_NETWORK_PROVIDER", "ddgs"),
                timeout_seconds=float(os.getenv("MOSAIC_NETWORK_TIMEOUT_SECONDS", "10")),
                max_response_bytes=int(os.getenv("MOSAIC_NETWORK_MAX_RESPONSE_BYTES", "2000000")),
                allowed_domains=_csv(os.getenv("MOSAIC_NETWORK_ALLOWED_DOMAINS")),
            ),
            filesystem=FilesystemConfig(
                enabled=_bool(os.getenv("MOSAIC_FILESYSTEM_ENABLED")),
                roots=_csv(os.getenv("MOSAIC_FILESYSTEM_ROOTS")),
                max_read_bytes=int(os.getenv("MOSAIC_FILESYSTEM_MAX_READ_BYTES", "1000000")),
            ),
            documents=DocumentsConfig(
                enabled=_bool(os.getenv("MOSAIC_DOCUMENTS_ENABLED")),
                max_pages=int(os.getenv("MOSAIC_DOCUMENTS_MAX_PAGES", "50")),
                max_output_chars=int(os.getenv("MOSAIC_DOCUMENTS_MAX_OUTPUT_CHARS", "200000")),
            ),
            builtins=BuiltinsConfig(
                tools_enabled=_bool(os.getenv("MOSAIC_BUILTIN_TOOLS_ENABLED"), default=True),
                skills_enabled=_bool(os.getenv("MOSAIC_BUILTIN_SKILLS_ENABLED"), default=True),
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
