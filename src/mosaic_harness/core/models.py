from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel

from .errors import InvalidAgentSpecError, InvalidModelSpecError

_AGENT_NAME = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")


@dataclass(frozen=True, slots=True)
class RunContext:
    user_id: str
    session_id: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.user_id.strip():
            raise ValueError("user_id must not be empty")
        if not self.session_id.strip():
            raise ValueError("session_id must not be empty")
        object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    """Provider/model capabilities; None means the capability is unknown."""

    tool_calling: bool | None = None
    streaming: bool | None = None
    structured_output: bool | None = None
    parallel_tool_calls: bool | None = None
    reasoning: bool | None = None

    def __post_init__(self) -> None:
        for name in (
            "tool_calling",
            "streaming",
            "structured_output",
            "parallel_tool_calls",
            "reasoning",
        ):
            value = getattr(self, name)
            if value is not None and not isinstance(value, bool):
                raise ValueError(f"model capability '{name}' must be a bool or None")


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """Declarative model configuration resolved by :class:`ModelFactory`."""

    provider: str
    model: str
    base_url: str | None = None
    api_key: str | None = field(default=None, repr=False)
    api_key_env: str | None = None
    default_headers: Mapping[str, str] = field(default_factory=dict, repr=False)
    temperature: float | None = None
    max_tokens: int | None = None
    timeout: float | None = None
    max_retries: int | None = None
    params: Mapping[str, Any] = field(default_factory=dict, repr=False)
    capabilities: ModelCapabilities | None = None

    def __post_init__(self) -> None:
        if not self.provider or not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", self.provider):
            raise InvalidModelSpecError("model provider must match [a-z][a-z0-9_-]{0,31}")
        if not self.model.strip():
            raise InvalidModelSpecError("model name must not be empty")
        if self.base_url is not None:
            from urllib.parse import urlparse

            parsed = urlparse(self.base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise InvalidModelSpecError("base_url must be an absolute http(s) URL")
        if self.api_key_env is not None and not re.fullmatch(r"[A-Z][A-Z0-9_]*", self.api_key_env):
            raise InvalidModelSpecError(
                "api_key_env must be an uppercase environment variable name"
            )
        for name, value in (
            ("max_tokens", self.max_tokens),
            ("max_retries", self.max_retries),
        ):
            if value is not None and value < 0:
                raise InvalidModelSpecError(f"{name} must be non-negative")
        if self.timeout is not None and self.timeout <= 0:
            raise InvalidModelSpecError("timeout must be positive")
        object.__setattr__(self, "default_headers", dict(self.default_headers))
        object.__setattr__(self, "params", dict(self.params))


ModelInput = str | BaseChatModel | ModelSpec


@dataclass(frozen=True, slots=True)
class AgentSpec:
    name: str
    system_prompt: str
    model: ModelInput | None = None
    description: str = ""
    tool_names: tuple[str, ...] = ()
    enabled_capabilities: tuple[str, ...] | None = None
    memory_namespace: str | None = None
    response_format: Any | None = None
    tags: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    recursion_limit: int | None = None

    def __post_init__(self) -> None:
        if not _AGENT_NAME.fullmatch(self.name):
            raise InvalidAgentSpecError("agent name must match ^[a-z][a-z0-9_-]{1,63}$")
        if not self.system_prompt.strip():
            raise InvalidAgentSpecError("system_prompt must not be empty")
        if self.memory_namespace is None:
            object.__setattr__(self, "memory_namespace", self.name)
        elif not self.memory_namespace.strip():
            raise InvalidAgentSpecError("memory_namespace must not be empty")
        object.__setattr__(self, "tool_names", tuple(self.tool_names))
        object.__setattr__(self, "tags", tuple(self.tags))
        object.__setattr__(self, "metadata", dict(self.metadata))
        if self.recursion_limit is not None and self.recursion_limit < 1:
            raise InvalidAgentSpecError("recursion_limit must be positive")


@dataclass(frozen=True, slots=True)
class ToolCallRecord:
    id: str
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class MessageRecord:
    role: Literal["system", "user", "assistant", "tool", "unknown"]
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: tuple[ToolCallRecord, ...] = ()
    content_blocks: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class RunResult:
    agent_name: str
    thread_id: str
    output_text: str
    messages: tuple[MessageRecord, ...]
    structured_response: Any | None = None
    model_provider: str | None = None
    model_name: str | None = None
    usage_metadata: Mapping[str, Any] = field(default_factory=dict)
    response_metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HarnessEvent:
    type: str
    agent_name: str
    thread_id: str
    run_id: str
    data: Mapping[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
