from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any
from uuid import uuid4

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from ..capabilities.mcp.client import MCPToolProvider
from ..capabilities.memory.store import MosaicMemory
from ..capabilities.observability.langsmith import LangSmithObservability
from ..capabilities.tools.registry import ToolRegistry
from ..config import MosaicConfig
from ..models import ModelFactory
from .errors import DuplicateAgentError, UnknownAgentError, UnsupportedModelCapabilityError
from .manager import CapabilityManager
from .models import (
    AgentSpec,
    HarnessEvent,
    MessageRecord,
    ModelSpec,
    RunContext,
    RunResult,
    ToolCallRecord,
)


class MosaicHarness:
    """Core runtime that assembles only the capabilities enabled for each agent."""

    def __init__(
        self,
        *,
        config: MosaicConfig | None = None,
        memory: MosaicMemory | None = None,
        checkpointer: BaseCheckpointSaver[Any] | None = None,
        observability: LangSmithObservability | None = None,
        model_factory: ModelFactory | None = None,
    ) -> None:
        self.config = config or MosaicConfig.from_env()
        self.memory = memory or MosaicMemory.in_memory()
        self.observability = observability or LangSmithObservability(
            enabled=self.config.observability.enabled,
            project_name=self.config.observability.project_name,
            tags=self.config.observability.tags,
            metadata=self.config.observability.metadata,
        )
        self._checkpointer = checkpointer or InMemorySaver()
        self._model_factory = model_factory or ModelFactory()
        self._tools = ToolRegistry()
        self._capabilities = CapabilityManager(
            self.config,
            self._tools,
            self.memory,
            self.observability,
        )
        self._agents: dict[str, AgentSpec] = {}
        self._compiled: dict[str, tuple[str, Any]] = {}
        self._resolved_models: dict[str, tuple[str, Any]] = {}

    @property
    def tools(self) -> ToolRegistry:
        return self._tools

    @property
    def capabilities(self) -> CapabilityManager:
        return self._capabilities

    @property
    def agent_names(self) -> tuple[str, ...]:
        return tuple(self._agents)

    def define(self, spec: AgentSpec) -> AgentSpec:
        if spec.model is None:
            raise ValueError(f"agent '{spec.name}' requires a model")
        if spec.name in self._agents:
            raise DuplicateAgentError(f"agent already defined: {spec.name}")
        self._capabilities.validate(spec)
        self._agents[spec.name] = spec
        return spec

    async def load_mcp(self, provider: MCPToolProvider) -> tuple[str, ...]:
        loaded = self._tools.register_many(await provider.load_tools())
        self._compiled.clear()
        return tuple(tool.name for tool in loaded)

    def invoke(
        self,
        agent_name: str,
        prompt: str,
        *,
        context: RunContext,
        thread_id: str,
        tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> RunResult:
        spec = self._spec(agent_name)
        graph, _ = self._graph(spec)
        config = self._run_config(
            spec,
            context,
            thread_id=thread_id,
            tags=tags,
            metadata=metadata,
        )
        with self.observability.tracing():
            state = graph.invoke(
                {"messages": [{"role": "user", "content": prompt}]},
                config=config,
                context=context,
            )
        return self._result(spec, thread_id, state)

    async def ainvoke(
        self,
        agent_name: str,
        prompt: str,
        *,
        context: RunContext,
        thread_id: str,
        tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> RunResult:
        spec = self._spec(agent_name)
        graph, _ = self._graph(spec)
        config = self._run_config(
            spec,
            context,
            thread_id=thread_id,
            tags=tags,
            metadata=metadata,
        )
        with self.observability.tracing():
            state = await graph.ainvoke(
                {"messages": [{"role": "user", "content": prompt}]},
                config=config,
                context=context,
            )
        return self._result(spec, thread_id, state)

    async def astream_events(
        self,
        agent_name: str,
        prompt: str,
        *,
        context: RunContext,
        thread_id: str,
        tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
    ) -> AsyncIterator[HarnessEvent]:
        spec = self._spec(agent_name)
        graph, _ = self._graph(spec)
        config = self._run_config(
            spec,
            context,
            thread_id=thread_id,
            tags=tags,
            metadata=metadata,
        )
        root_run_id = str(uuid4())
        yield HarnessEvent(
            type="run.started",
            agent_name=spec.name,
            thread_id=thread_id,
            run_id=root_run_id,
            data={"prompt": prompt},
        )
        try:
            with self.observability.tracing():
                async for event in graph.astream_events(
                    {"messages": [{"role": "user", "content": prompt}]},
                    config=config,
                    context=context,
                    version="v2",
                ):
                    normalized = _normalize_event(event, spec.name, thread_id)
                    if normalized is not None:
                        yield normalized
        except Exception as exc:
            yield HarnessEvent(
                type="run.failed",
                agent_name=spec.name,
                thread_id=thread_id,
                run_id=root_run_id,
                data={"error_type": type(exc).__name__, "message": str(exc)},
            )
            raise
        yield HarnessEvent(
            type="run.completed",
            agent_name=spec.name,
            thread_id=thread_id,
            run_id=root_run_id,
        )

    def _spec(self, name: str) -> AgentSpec:
        try:
            return self._agents[name]
        except KeyError as exc:
            raise UnknownAgentError(f"unknown agent: {name}") from exc

    def _graph(self, spec: AgentSpec) -> tuple[Any, tuple[str, ...]]:
        if spec.model is None:
            raise ValueError(f"agent '{spec.name}' requires a model")
        model_fingerprint = self._model_factory.fingerprint(spec.model)
        model = self._resolved_model(spec.name, spec.model, model_fingerprint)
        compaction_model = None
        compaction_fingerprint = "none"
        if self.config.compaction.model is not None:
            compaction_input = self.config.compaction.model
            compaction_fingerprint = self._model_factory.fingerprint(compaction_input)
            compaction_model = self._resolved_model(
                f"{spec.name}:compaction", compaction_input, compaction_fingerprint
            )
        assembly = self._capabilities.assemble(
            spec,
            model=model,
            compaction_model=compaction_model,
        )
        capabilities = self._model_factory.describe(spec.model)
        if assembly.tools and capabilities.tool_calling is False:
            raise UnsupportedModelCapabilityError(
                f"model '{_model_label(spec)}' does not support tool calling"
            )
        if spec.response_format is not None and capabilities.structured_output is False:
            raise UnsupportedModelCapabilityError(
                f"model '{_model_label(spec)}' does not support structured output"
            )
        cached = self._compiled.get(spec.name)
        cache_key = repr(
            (
                model_fingerprint,
                compaction_fingerprint,
                self._tools.version,
                hash(assembly.system_prompt),
                tuple(type(item).__qualname__ for item in assembly.middleware),
            )
        )
        if cached is not None and cached[0] == cache_key:
            return cached[1], assembly.enabled_capabilities
        has_memory = "memory" in assembly.enabled_capabilities
        graph = create_agent(
            model=model,
            tools=list(assembly.tools),
            system_prompt=assembly.system_prompt,
            middleware=list(assembly.middleware),
            response_format=spec.response_format,
            context_schema=RunContext,
            checkpointer=self._checkpointer if has_memory else None,
            store=self.memory.native_store if has_memory else None,
            name=spec.name,
        )
        self._compiled[spec.name] = (cache_key, graph)
        return graph, assembly.enabled_capabilities

    def _resolved_model(self, key: str, model_input: Any, fingerprint: str) -> Any:
        cached = self._resolved_models.get(key)
        if cached is not None and cached[0] == fingerprint:
            return cached[1]
        model = self._model_factory.resolve(model_input)
        self._resolved_models[key] = (fingerprint, model)
        return model

    def _run_config(
        self,
        spec: AgentSpec,
        context: RunContext,
        *,
        thread_id: str,
        tags: Sequence[str],
        metadata: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        config = self.observability.run_config(
            spec,
            context,
            thread_id=thread_id,
            tags=tags,
            metadata=metadata,
        )
        config["configurable"] = {"thread_id": f"{context.user_id}:{thread_id}"}
        return config

    @staticmethod
    def _result(spec: AgentSpec, thread_id: str, state: Mapping[str, Any]) -> RunResult:
        raw_messages = tuple(
            message for message in state.get("messages", ()) if isinstance(message, BaseMessage)
        )
        messages = tuple(_message_record(message) for message in raw_messages)
        output_text = next(
            (message.content for message in reversed(messages) if message.role == "assistant"),
            "",
        )
        last_ai = next(
            (message for message in reversed(raw_messages) if isinstance(message, AIMessage)),
            None,
        )
        response_metadata = getattr(last_ai, "response_metadata", {}) if last_ai else {}
        usage_metadata = getattr(last_ai, "usage_metadata", {}) if last_ai else {}
        response_metadata = (
            dict(response_metadata) if isinstance(response_metadata, Mapping) else {}
        )
        usage_metadata = dict(usage_metadata) if isinstance(usage_metadata, Mapping) else {}
        model_provider = _metadata_string(response_metadata, "model_provider")
        model_name = _metadata_string(response_metadata, "model")
        if isinstance(spec.model, ModelSpec):
            model_provider = model_provider or spec.model.provider
            model_name = model_name or spec.model.model
        elif isinstance(spec.model, str):
            provider, separator, name = spec.model.partition(":")
            model_provider = model_provider or (provider if separator else None)
            model_name = model_name or (name if separator else spec.model)
        return RunResult(
            agent_name=spec.name,
            thread_id=thread_id,
            output_text=output_text,
            messages=messages,
            structured_response=state.get("structured_response"),
            model_provider=model_provider,
            model_name=model_name,
            usage_metadata=usage_metadata,
            response_metadata=response_metadata,
        )


def _message_record(message: BaseMessage) -> MessageRecord:
    role = {
        "system": "system",
        "human": "user",
        "ai": "assistant",
        "tool": "tool",
    }.get(message.type, "unknown")
    tool_calls: tuple[ToolCallRecord, ...] = ()
    if isinstance(message, AIMessage):
        tool_calls = tuple(
            ToolCallRecord(
                id=str(call.get("id", "")),
                name=str(call.get("name", "")),
                arguments=dict(call.get("args", {})),
            )
            for call in message.tool_calls
        )
    return MessageRecord(
        role=role,  # type: ignore[arg-type]
        content=_content_text(message.content),
        name=getattr(message, "name", None),
        tool_call_id=getattr(message, "tool_call_id", None),
        tool_calls=tool_calls,
        content_blocks=_content_blocks(message.content),
    )


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, Mapping):
                if block.get("type") in {"thinking", "reasoning"}:
                    continue
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    if isinstance(content, Mapping):
        if content.get("type") in {"thinking", "reasoning"}:
            return ""
        text = content.get("text")
        if isinstance(text, str):
            return text
    return str(content)


def _content_blocks(content: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(content, list):
        return ()
    return tuple(dict(block) for block in content if isinstance(block, Mapping))


def _metadata_string(metadata: Mapping[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    return str(value) if value is not None else None


def _model_label(spec: AgentSpec) -> str:
    model = spec.model
    if isinstance(model, str):
        return model
    if isinstance(model, ModelSpec):
        return f"{model.provider}:{model.model}"
    return type(model).__name__ if model is not None else "unknown"


def _normalize_event(
    event: Mapping[str, Any],
    agent_name: str,
    thread_id: str,
) -> HarnessEvent | None:
    event_type = {
        "on_chat_model_start": "model.started",
        "on_chat_model_stream": "model.delta",
        "on_chat_model_end": "model.completed",
        "on_tool_start": "tool.started",
        "on_tool_end": "tool.completed",
        "on_tool_error": "tool.failed",
    }.get(str(event.get("event")))
    if event_type is None:
        return None
    data = event.get("data", {})
    safe_data: dict[str, Any] = {}
    if event_type == "model.delta":
        chunk = data.get("chunk") if isinstance(data, Mapping) else None
        safe_data["content"] = _content_text(getattr(chunk, "content", ""))
    elif event_type.startswith("tool."):
        safe_data["tool_name"] = str(event.get("name", ""))
        if isinstance(data, Mapping):
            if "input" in data:
                safe_data["input"] = _json_safe(data["input"])
            if "output" in data:
                safe_data["output"] = _json_safe(data["output"])
            if "error" in data:
                safe_data["error"] = str(data["error"])
    return HarnessEvent(
        type=event_type,
        agent_name=agent_name,
        thread_id=thread_id,
        run_id=str(event.get("run_id", "")),
        data=safe_data,
    )


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return str(value)
    return value
