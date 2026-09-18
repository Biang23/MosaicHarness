from __future__ import annotations

import logging

import pytest
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import AIMessage

from mosaic_harness import (
    AgentSpec,
    MemoryConfig,
    ModelCapabilities,
    ModelFactory,
    ModelSpec,
    MosaicConfig,
    MosaicHarness,
    RunContext,
    ToolsConfig,
)
from mosaic_harness.core.errors import (
    DuplicateAgentError,
    DuplicateToolError,
    InvalidAgentSpecError,
    UnknownAgentError,
    UnknownToolError,
)
from mosaic_harness.core.runtime import _message_record, _normalize_event

from .fakes import CountingChatModel, ScriptedChatModel


class RuntimeFakeProvider:
    name = "runtime-fake"
    optional_dependency = "runtime-fake"
    install_extra = "dev"

    def __init__(self, *, capabilities: ModelCapabilities) -> None:
        self.capabilities = capabilities
        self.build_count = 0

    def build(self, spec: ModelSpec) -> ScriptedChatModel:
        del spec
        self.build_count += 1
        return ScriptedChatModel(
            responses=[AIMessage(content="factory response") for _ in range(4)]
        )

    def describe(self, spec: ModelSpec) -> ModelCapabilities:
        del spec
        return self.capabilities


def tools_config() -> MosaicConfig:
    return MosaicConfig(
        enabled_capabilities=("tools",),
        tools=ToolsConfig(enabled=True),
    )


def memory_config() -> MosaicConfig:
    return MosaicConfig(
        enabled_capabilities=("memory", "tools"),
        memory=MemoryConfig(enabled=True),
        tools=ToolsConfig(enabled=True),
    )


@tool
def current_user(runtime: ToolRuntime[RunContext]) -> str:
    """Return the current runtime user identifier."""
    return runtime.context.user_id


def test_agent_executes_a_tool_with_injected_context() -> None:
    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"name": "current_user", "args": {}, "id": "call-1"}],
            ),
            AIMessage(content="The current user is u-42."),
        ]
    )
    sdk = MosaicHarness(config=tools_config())
    sdk.tools.register(current_user)
    sdk.define(
        AgentSpec(
            name="identity",
            system_prompt="Use the tool.",
            model=model,
            tool_names=("current_user",),
        )
    )

    result = sdk.invoke(
        "identity",
        "Who am I?",
        context=RunContext(user_id="u-42", session_id="s-1"),
        thread_id="thread-1",
    )

    assert result.output_text == "The current user is u-42."
    tool_messages = [message for message in result.messages if message.role == "tool"]
    assert tool_messages[0].content == "u-42"
    assert tool_messages[0].tool_call_id == "call-1"


def test_thread_checkpointer_is_enabled_by_memory_capability() -> None:
    model = CountingChatModel()
    sdk = MosaicHarness(config=memory_config())
    sdk.define(
        AgentSpec(
            name="counter",
            system_prompt="Count conversation messages.",
            model=model,
        )
    )
    context = RunContext(user_id="u-1", session_id="s-1")

    first = sdk.invoke("counter", "first", context=context, thread_id="same")
    second = sdk.invoke("counter", "second", context=context, thread_id="same")
    isolated = sdk.invoke("counter", "other", context=context, thread_id="different")

    assert first.output_text == "human_messages=1"
    assert second.output_text == "human_messages=2"
    assert isolated.output_text == "human_messages=1"


def test_short_term_memory_is_scoped_by_user_even_when_thread_ids_match() -> None:
    model = CountingChatModel()
    sdk = MosaicHarness(config=memory_config())
    sdk.define(AgentSpec(name="scoped-counter", system_prompt="Count.", model=model))

    first = sdk.invoke(
        "scoped-counter",
        "first",
        context=RunContext(user_id="u-1", session_id="s-1"),
        thread_id="shared-id",
    )
    second = sdk.invoke(
        "scoped-counter",
        "second",
        context=RunContext(user_id="u-2", session_id="s-2"),
        thread_id="shared-id",
    )

    assert first.output_text == "human_messages=1"
    assert second.output_text == "human_messages=1"


@pytest.mark.asyncio
async def test_async_invoke_uses_the_same_public_result_contract() -> None:
    sdk = MosaicHarness()
    sdk.define(
        AgentSpec(
            name="async-agent",
            system_prompt="Answer.",
            model=ScriptedChatModel(responses=[AIMessage(content="async done")]),
        )
    )

    result = await sdk.ainvoke(
        "async-agent",
        "hello",
        context=RunContext(user_id="u-1", session_id="s-1"),
        thread_id="async-thread",
    )

    assert result.output_text == "async done"


def test_invoke_logs_run_lifecycle_without_logging_prompt_or_output(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sdk = MosaicHarness()
    sdk.define(
        AgentSpec(
            name="logged-agent",
            system_prompt="Answer.",
            model=ScriptedChatModel(responses=[AIMessage(content="secret output")]),
        )
    )

    with caplog.at_level(logging.INFO, logger="mosaic_harness"):
        sdk.invoke(
            "logged-agent",
            "secret prompt",
            context=RunContext(user_id="u-1", session_id="s-1"),
            thread_id="logged-thread",
        )

    messages = [record.getMessage() for record in caplog.records]
    assert any("run.started" in message for message in messages)
    assert any("run.completed" in message for message in messages)
    assert all(secret not in caplog.text for secret in ("secret prompt", "secret output"))


def test_define_validates_capabilities_and_names() -> None:
    sdk = MosaicHarness()
    with pytest.raises(ValueError):
        sdk.define(AgentSpec(name="missing-model", system_prompt="x"))
    sdk.define(
        AgentSpec(
            name="defined",
            system_prompt="x",
            model=ScriptedChatModel(responses=[AIMessage(content="ok")]),
        )
    )
    with pytest.raises(DuplicateAgentError):
        sdk.define(
            AgentSpec(
                name="defined",
                system_prompt="x",
                model=ScriptedChatModel(responses=[AIMessage(content="ok")]),
            )
        )
    with pytest.raises(UnknownToolError):
        MosaicHarness(config=tools_config()).define(
            AgentSpec(
                name="unknown-tool",
                system_prompt="x",
                model=ScriptedChatModel(responses=[AIMessage(content="ok")]),
                tool_names=("missing",),
            )
        )
    with pytest.raises(InvalidAgentSpecError):
        MosaicHarness().define(
            AgentSpec(
                name="tool-capability-off",
                system_prompt="x",
                model=ScriptedChatModel(responses=[AIMessage(content="ok")]),
                tool_names=("missing",),
            )
        )


def test_agent_cannot_shadow_builtin_memory_tools() -> None:
    with pytest.raises(DuplicateToolError, match="built-in memory tools"):
        MosaicHarness(config=memory_config()).define(
            AgentSpec(
                name="memory-shadow",
                system_prompt="x",
                model=ScriptedChatModel(responses=[AIMessage(content="ok")]),
                tool_names=("memory_search",),
            )
        )


def test_builtin_memory_tool_writes_namespaced_long_term_memory() -> None:
    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "memory_write",
                        "args": {"key": "preference", "content": "Prefers concise answers"},
                        "id": "memory-call",
                    }
                ],
            ),
            AIMessage(content="Remembered."),
        ]
    )
    sdk = MosaicHarness(config=memory_config())
    sdk.define(AgentSpec(name="assistant", system_prompt="Remember facts.", model=model))

    sdk.invoke(
        "assistant",
        "Remember that I prefer concise answers.",
        context=RunContext(user_id="u-1", session_id="s-1"),
        thread_id="thread-memory",
    )

    item = sdk.memory.get(("mosaic", "assistant", "u-1"), "preference")
    assert item == {"content": "Prefers concise answers"}


def test_unknown_agent_fails_before_model_execution() -> None:
    with pytest.raises(UnknownAgentError):
        MosaicHarness().invoke(
            "missing",
            "hello",
            context=RunContext(user_id="u-1", session_id="s-1"),
            thread_id="t-1",
        )


@pytest.mark.asyncio
async def test_event_stream_is_normalized() -> None:
    sdk = MosaicHarness()
    sdk.define(
        AgentSpec(
            name="streamer",
            system_prompt="Answer.",
            model=ScriptedChatModel(responses=[AIMessage(content="done")]),
        )
    )

    events = [
        event
        async for event in sdk.astream_events(
            "streamer",
            "hello",
            context=RunContext(user_id="u-1", session_id="s-1"),
            thread_id="stream-thread",
        )
    ]

    assert events[0].type == "run.started"
    assert events[-1].type == "run.completed"
    assert all(event.agent_name == "streamer" for event in events)


@pytest.mark.asyncio
async def test_event_stream_includes_tool_lifecycle_events() -> None:
    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"name": "current_user", "args": {}, "id": "event-call"}],
            ),
            AIMessage(content="done"),
        ]
    )
    sdk = MosaicHarness(config=tools_config())
    sdk.tools.register(current_user)
    sdk.define(
        AgentSpec(
            name="event-tool",
            system_prompt="Use the tool.",
            model=model,
            tool_names=("current_user",),
        )
    )

    events = [
        event
        async for event in sdk.astream_events(
            "event-tool",
            "hello",
            context=RunContext(user_id="u-1", session_id="s-1"),
            thread_id="event-thread",
        )
    ]

    event_types = [event.type for event in events]
    assert "tool.started" in event_types
    assert "tool.completed" in event_types
    assert "model.started" in event_types


def test_event_normalizer_keeps_payloads_json_safe() -> None:
    model_event = _normalize_event(
        {
            "event": "on_chat_model_stream",
            "run_id": "model-run",
            "data": {"chunk": AIMessage(content=[{"text": "delta"}])},
        },
        "agent",
        "thread",
    )
    tool_event = _normalize_event(
        {
            "event": "on_tool_error",
            "run_id": "tool-run",
            "name": "dangerous_tool",
            "data": {"input": object(), "error": RuntimeError("failed")},
        },
        "agent",
        "thread",
    )

    assert model_event is not None
    assert model_event.data["content"] == "delta"
    assert tool_event is not None
    assert tool_event.data["tool_name"] == "dangerous_tool"
    assert tool_event.data["error"] == "failed"


def test_message_record_extracts_visible_text_from_reasoning_blocks() -> None:
    message = AIMessage(
        content=[
            {"type": "thinking", "thinking": "private reasoning"},
            {"type": "text", "text": "visible answer"},
        ]
    )

    record = _message_record(message)

    assert record.content == "visible answer"
    assert record.content_blocks == (
        {"type": "thinking", "thinking": "private reasoning"},
        {"type": "text", "text": "visible answer"},
    )


def test_result_exposes_provider_and_usage_metadata_without_changing_text() -> None:
    spec = AgentSpec(name="metadata-agent", system_prompt="Answer.")
    state = {
        "messages": [
            AIMessage(
                content="done",
                response_metadata={"model_provider": "anthropic", "model": "claude-test"},
                usage_metadata={"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
            )
        ]
    }

    result = MosaicHarness._result(spec, "thread", state)

    assert result.output_text == "done"
    assert result.model_provider == "anthropic"
    assert result.model_name == "claude-test"
    assert result.usage_metadata["total_tokens"] == 5


def test_runtime_resolves_declarative_model_once_and_reuses_the_graph() -> None:
    provider = RuntimeFakeProvider(
        capabilities=ModelCapabilities(tool_calling=True, structured_output=True)
    )
    factory = ModelFactory()
    factory.register(provider)
    sdk = MosaicHarness(model_factory=factory)
    sdk.define(
        AgentSpec(
            name="factory-agent",
            system_prompt="Answer.",
            model=ModelSpec(provider="runtime-fake", model="test"),
        )
    )
    context = RunContext(user_id="u-1", session_id="s-1")

    first = sdk.invoke("factory-agent", "hello", context=context, thread_id="t-1")
    second = sdk.invoke("factory-agent", "hello", context=context, thread_id="t-2")

    assert first.output_text == "factory response"
    assert second.output_text == "factory response"
    assert provider.build_count == 1


def test_runtime_rejects_explicitly_unsupported_structured_output() -> None:
    provider = RuntimeFakeProvider(capabilities=ModelCapabilities(structured_output=False))
    factory = ModelFactory()
    factory.register(provider)
    sdk = MosaicHarness(model_factory=factory)
    sdk.define(
        AgentSpec(
            name="no-structure",
            system_prompt="Answer.",
            model=ModelSpec(provider="runtime-fake", model="test"),
            response_format=object,
        )
    )

    with pytest.raises(ValueError, match="structured output"):
        sdk.invoke(
            "no-structure",
            "hello",
            context=RunContext(user_id="u-1", session_id="s-1"),
            thread_id="t-1",
        )

    assert provider.build_count == 1


def test_doctor_reports_model_capability_mismatch_without_invoking_model() -> None:
    provider = RuntimeFakeProvider(
        capabilities=ModelCapabilities(tool_calling=False, structured_output=False)
    )
    factory = ModelFactory()
    factory.register(provider)
    sdk = MosaicHarness(config=tools_config(), model_factory=factory)
    sdk.tools.register(current_user)
    sdk.define(
        AgentSpec(
            name="doctor-agent",
            system_prompt="Use the tool.",
            model=ModelSpec(provider="runtime-fake", model="test"),
            tool_names=("current_user",),
        )
    )

    report = sdk.doctor("doctor-agent")

    assert report.ok is False
    assert report.model_provider == "runtime-fake"
    assert report.requirements.tool_calling is True
    assert any(check.status == "unsupported" for check in report.checks)
    assert provider.build_count == 0
