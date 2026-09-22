from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import replace
from importlib.util import find_spec
from typing import Any, Literal, cast
from uuid import uuid4

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

from ..capabilities.builtins.base import MosaicSkill
from ..capabilities.mcp.client import MCPToolProvider
from ..capabilities.memory.store import MosaicMemory
from ..capabilities.observability.langsmith import LangSmithObservability
from ..capabilities.security.approval import ApprovalService
from ..capabilities.security.policy import SecurityPolicy
from ..capabilities.tools.execution import (
    ToolExecutionMiddleware,
    ToolExecutionPolicy,
    ToolExecutionRecorder,
)
from ..capabilities.tools.registry import ToolRegistry
from ..config import MosaicConfig
from ..evaluation import Dataset, DatasetFactory, EvaluationReport, Evaluator
from ..models import ModelFactory
from ..models.capabilities import (
    CapabilityCheck,
    CapabilityStatus,
    CategoryCheck,
    ModelDoctorReport,
    ModelRequirements,
)
from ..models.router import ModelRouter, ModelRoutingDecision
from .analytics import RunAnalytics
from .errors import DuplicateAgentError, UnknownAgentError, UnsupportedModelCapabilityError
from .journal import InMemoryRunJournal, RunJournal
from .manager import CapabilityManager
from .models import (
    AgentManifest,
    AgentSpec,
    HarnessEvent,
    MessageRecord,
    ModelInput,
    ModelSpec,
    RunContext,
    RunResult,
    ToolCallRecord,
)
from .replay import ReplayResult
from .retry import ToolRetryResult

logger = logging.getLogger(__name__)


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
        tool_policies: Mapping[str, ToolExecutionPolicy] | None = None,
        tool_recorder: ToolExecutionRecorder | None = None,
        journal: RunJournal | None = None,
        security_policy: SecurityPolicy | None = None,
        approval_service: ApprovalService | None = None,
        model_router: ModelRouter | None = None,
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
        self._tool_policies = dict(tool_policies or {})
        self._tool_recorder = tool_recorder or ToolExecutionRecorder()
        self._journal = journal or InMemoryRunJournal()
        self._security_policy = security_policy
        self._approval_service = approval_service
        self._model_router = model_router or ModelRouter(self._model_factory)
        self._dataset = DatasetFactory(self._journal)
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
        logger.debug(
            "harness.initialized capabilities=%s tools=%d",
            self.config.enabled_capabilities,
            len(self._tools.names),
        )

    @property
    def tools(self) -> ToolRegistry:
        return self._tools

    @property
    def capabilities(self) -> CapabilityManager:
        return self._capabilities

    @property
    def agent_names(self) -> tuple[str, ...]:
        return tuple(self._agents)

    def manifest(self, agent_name: str) -> AgentManifest:
        spec = self._spec(agent_name)
        enabled = self._capabilities.enabled_names(spec)
        model = _model_label(spec) if spec.model is not None else None
        tools = tuple(dict.fromkeys((*self._tools.builtin_names, *spec.tool_names)))
        return AgentManifest(
            name=spec.name,
            description=spec.description,
            model=model,
            enabled_capabilities=enabled,
            tools=tools,
        )

    def manifests(self) -> tuple[AgentManifest, ...]:
        return tuple(self.manifest(name) for name in self.agent_names)

    def close(self) -> None:
        """Release closeable resources owned by the Harness."""
        closer = getattr(self._journal, "close", None)
        if callable(closer):
            closer()

    def __enter__(self) -> MosaicHarness:
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        del exc_type, exc_value, traceback
        self.close()

    async def __aenter__(self) -> MosaicHarness:
        return self

    async def __aexit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        del exc_type, exc_value, traceback
        self.close()

    @property
    def tool_records(self) -> tuple[Any, ...]:
        return self._tool_recorder.records

    @property
    def journal(self) -> RunJournal:
        return self._journal

    def analytics(self, run_id: str) -> RunAnalytics:
        events = self._journal.events(run_id)
        if not events:
            raise ValueError(f"no journal events found for run '{run_id}'")
        return RunAnalytics.from_events(run_id, events)

    def delegate(
        self,
        agent_name: str,
        prompt: str,
        *,
        context: RunContext,
        thread_id: str,
        parent_run_id: str,
    ) -> RunResult:
        """Run a child Agent while linking its Journal events to a parent run."""
        return self.invoke(
            agent_name,
            prompt,
            context=context,
            thread_id=thread_id,
            parent_run_id=parent_run_id,
        )

    async def adelegate(
        self,
        agent_name: str,
        prompt: str,
        *,
        context: RunContext,
        thread_id: str,
        parent_run_id: str,
    ) -> RunResult:
        """Async counterpart of :meth:`delegate`."""
        return await self.ainvoke(
            agent_name,
            prompt,
            context=context,
            thread_id=thread_id,
            parent_run_id=parent_run_id,
        )

    def route_model(
        self, candidates: Sequence[ModelInput], spec: AgentSpec
    ) -> ModelRoutingDecision:
        """Preview offline model routing for an AgentSpec."""
        tool_count = len(set(spec.tool_names).union(self._tools.builtin_names))
        return self._model_router.select_for_agent(candidates, spec, tool_count=tool_count)

    @property
    def dataset(self) -> DatasetFactory:
        return self._dataset

    def evaluate(
        self,
        dataset: Dataset,
        evaluators: Sequence[Evaluator],
        *,
        release_gate: float = 1.0,
    ) -> EvaluationReport:
        from ..evaluation import evaluate_dataset

        return evaluate_dataset(dataset, evaluators, release_gate=release_gate)

    def replay(self, run_id: str, *, mode: Literal["recorded"] = "recorded") -> ReplayResult:
        """Replay journaled events without resolving a model or executing a tool."""
        if mode != "recorded":
            raise ValueError("only recorded replay is supported")
        events = self._journal.events(run_id)
        if not events:
            raise ValueError(f"no journal events found for run '{run_id}'")
        return ReplayResult(run_id=run_id, mode=mode, events=events)

    def retry_tool(self, run_id: str, tool_call_id: str) -> ToolRetryResult:
        """Retry one recorded failed Tool call without invoking the model."""
        events = self._journal.events(run_id)
        started = next(
            (
                event
                for event in events
                if event.type == "tool.started" and event.run_id == tool_call_id
            ),
            None,
        )
        failed = next(
            (
                event
                for event in events
                if event.type == "tool.failed" and event.run_id == tool_call_id
            ),
            None,
        )
        if started is None or failed is None:
            raise ValueError(f"no failed Tool call '{tool_call_id}' found in run '{run_id}'")
        tool_name = str(started.data.get("tool_name", ""))
        arguments = started.data.get("input", {})
        if not isinstance(arguments, Mapping):
            raise ValueError(f"recorded arguments for Tool call '{tool_call_id}' are not a mapping")
        tool = self._tools.resolve((tool_name,))[0]
        retry_call_id = f"{tool_call_id}:retry:{uuid4()}"
        self._record_event(
            HarnessEvent(
                "tool.retry.started",
                started.agent_name,
                started.thread_id,
                retry_call_id,
                {"tool_name": tool_name, "original_call_id": tool_call_id},
                parent_run_id=run_id,
            )
        )
        middleware = ToolExecutionMiddleware(
            policies=self._tool_policies,
            recorder=self._tool_recorder,
            security_policy=self._security_policy,
            tool_categories={tool.name: getattr(tool, "category", "core")},
            approval_service=self._approval_service,
        )
        try:
            output = middleware.execute_sync(
                tool_name=tool_name,
                call_id=retry_call_id,
                arguments=arguments,
                handler=lambda values: tool.invoke(cast(dict[str, Any], values)),
            )
        except Exception as exc:
            self._record_event(
                HarnessEvent(
                    "tool.retry.failed",
                    started.agent_name,
                    started.thread_id,
                    retry_call_id,
                    {"tool_name": tool_name, "error_type": type(exc).__name__},
                    parent_run_id=run_id,
                )
            )
            return ToolRetryResult(
                run_id,
                retry_call_id,
                tool_name,
                "error",
                error=f"{type(exc).__name__}: {exc}",
            )
        record = next(
            (
                item
                for item in reversed(self._tool_recorder.records)
                if item.call_id == retry_call_id
            ),
            None,
        )
        status: Literal["success", "error", "blocked"] = (
            "success"
            if record is None or record.status == "success"
            else "blocked"
            if record.status == "blocked"
            else "error"
        )
        event_type = "tool.retry.completed" if status == "success" else "tool.retry.failed"
        self._record_event(
            HarnessEvent(
                event_type,
                started.agent_name,
                started.thread_id,
                retry_call_id,
                {"tool_name": tool_name, "status": status},
                parent_run_id=run_id,
            )
        )
        return ToolRetryResult(run_id, retry_call_id, tool_name, status, output=output)

    def doctor(self, agent_name: str) -> ModelDoctorReport:
        spec = self._spec(agent_name)
        if spec.model is None:
            raise ValueError(f"agent '{spec.name}' requires a model")
        enabled = self._capabilities.enabled_names(spec)
        tool_count = len(set(spec.tool_names).union(self._tools.builtin_names))
        if "memory" in enabled:
            tool_count += 3
        if "skills" in enabled:
            tool_count += 2
        requirements = ModelRequirements.from_agent(spec, tool_count)
        inspection = self._model_factory.inspect(spec.model)
        checks = tuple(
            _capability_check(
                name,
                getattr(requirements, name),
                getattr(inspection.capabilities, name),
            )
            for name in (
                "tool_calling",
                "structured_output",
                "streaming",
                "parallel_tool_calls",
                "reasoning",
            )
        )
        recommendations: list[str] = []
        if not inspection.provider_installed:
            recommendations.append(f"Install the provider integration for '{inspection.provider}'.")
        if inspection.credential_env and not inspection.credential_configured:
            recommendations.append(
                f"Configure the '{inspection.credential_env}' environment variable."
            )
        for check in checks:
            if check.status == "unsupported":
                recommendations.append(
                    f"Use a model that supports {check.name} or disable the "
                    "corresponding Agent requirement."
                )
        category_checks = _category_checks(self.config)
        for category_check in category_checks:
            if category_check.status == "misconfigured":
                recommendations.append(category_check.message)
        return ModelDoctorReport(
            agent_name=spec.name,
            model_provider=inspection.provider,
            model_name=inspection.model,
            capabilities=inspection.capabilities,
            requirements=requirements,
            checks=checks,
            provider_installed=inspection.provider_installed,
            credential_env=inspection.credential_env,
            credential_configured=inspection.credential_configured,
            category_checks=category_checks,
            recommendations=tuple(recommendations),
        )

    def define(self, spec: AgentSpec) -> AgentSpec:
        if spec.model is None and not spec.model_candidates:
            raise ValueError(f"agent '{spec.name}' requires a model or model_candidates")
        if spec.model is not None and spec.model_candidates:
            raise ValueError("set either model or model_candidates, not both")
        if spec.model is None:
            decision = self._model_router.select_for_agent(
                spec.model_candidates,
                spec,
                tool_count=len(set(spec.tool_names).union(self._tools.builtin_names)),
            )
            spec = replace(spec, model=decision.selected)
        if spec.name in self._agents:
            raise DuplicateAgentError(f"agent already defined: {spec.name}")
        self._capabilities.validate(spec)
        self._agents[spec.name] = spec
        logger.info(
            "agent.defined agent=%s model=%s capabilities=%s",
            spec.name,
            _model_label(spec),
            spec.enabled_capabilities or self.config.enabled_capabilities,
        )
        return spec

    async def load_mcp(self, provider: MCPToolProvider) -> tuple[str, ...]:
        loaded = self._tools.register_many(await provider.load_tools())
        self._compiled.clear()
        return tuple(tool.name for tool in loaded)

    def register_skill(self, skill: MosaicSkill) -> None:
        self._capabilities.register_skill(skill)

    def invoke(
        self,
        agent_name: str,
        prompt: str,
        *,
        context: RunContext,
        thread_id: str,
        tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
        parent_run_id: str | None = None,
    ) -> RunResult:
        run_id = str(uuid4())
        logger.info(
            "run.started agent=%s thread_id=%s run_id=%s mode=sync",
            agent_name,
            thread_id,
            run_id,
        )
        self._record_event(
            HarnessEvent(
                "run.started",
                agent_name,
                thread_id,
                run_id,
                parent_run_id=parent_run_id,
            )
        )
        try:
            spec = self._spec(agent_name)
            graph, _, diagnostics = self._graph(spec)
            for diagnostic in diagnostics:
                self._record_event(
                    HarnessEvent("action_space.selected", spec.name, thread_id, run_id, diagnostic)
                )
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
            result = self._result(spec, thread_id, state, run_id=run_id)
            self._record_event(
                HarnessEvent(
                    "run.completed",
                    spec.name,
                    thread_id,
                    run_id,
                    parent_run_id=parent_run_id,
                )
            )
            logger.info(
                "run.completed agent=%s thread_id=%s run_id=%s output_chars=%d",
                agent_name,
                thread_id,
                run_id,
                len(result.output_text),
            )
            return result
        except Exception as exc:
            logger.error(
                "run.failed agent=%s thread_id=%s run_id=%s error_type=%s",
                agent_name,
                thread_id,
                run_id,
                type(exc).__name__,
            )
            self._record_event(
                HarnessEvent(
                    "run.failed",
                    agent_name,
                    thread_id,
                    run_id,
                    {"error_type": type(exc).__name__},
                    parent_run_id=parent_run_id,
                )
            )
            raise

    async def ainvoke(
        self,
        agent_name: str,
        prompt: str,
        *,
        context: RunContext,
        thread_id: str,
        tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
        parent_run_id: str | None = None,
    ) -> RunResult:
        run_id = str(uuid4())
        logger.info(
            "run.started agent=%s thread_id=%s run_id=%s mode=async",
            agent_name,
            thread_id,
            run_id,
        )
        self._record_event(
            HarnessEvent(
                "run.started",
                agent_name,
                thread_id,
                run_id,
                parent_run_id=parent_run_id,
            )
        )
        try:
            spec = self._spec(agent_name)
            graph, _, diagnostics = self._graph(spec)
            for diagnostic in diagnostics:
                self._record_event(
                    HarnessEvent("action_space.selected", spec.name, thread_id, run_id, diagnostic)
                )
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
            result = self._result(spec, thread_id, state, run_id=run_id)
            self._record_event(
                HarnessEvent(
                    "run.completed",
                    spec.name,
                    thread_id,
                    run_id,
                    parent_run_id=parent_run_id,
                )
            )
            logger.info(
                "run.completed agent=%s thread_id=%s run_id=%s output_chars=%d",
                agent_name,
                thread_id,
                run_id,
                len(result.output_text),
            )
            return result
        except Exception as exc:
            logger.error(
                "run.failed agent=%s thread_id=%s run_id=%s error_type=%s",
                agent_name,
                thread_id,
                run_id,
                type(exc).__name__,
            )
            self._record_event(
                HarnessEvent(
                    "run.failed",
                    agent_name,
                    thread_id,
                    run_id,
                    {"error_type": type(exc).__name__},
                    parent_run_id=parent_run_id,
                )
            )
            raise

    async def astream_events(
        self,
        agent_name: str,
        prompt: str,
        *,
        context: RunContext,
        thread_id: str,
        tags: Sequence[str] = (),
        metadata: Mapping[str, Any] | None = None,
        parent_run_id: str | None = None,
    ) -> AsyncIterator[HarnessEvent]:
        spec = self._spec(agent_name)
        graph, _, diagnostics = self._graph(spec)
        config = self._run_config(
            spec,
            context,
            thread_id=thread_id,
            tags=tags,
            metadata=metadata,
        )
        root_run_id = str(uuid4())
        logger.info(
            "run.started agent=%s thread_id=%s run_id=%s mode=events",
            agent_name,
            thread_id,
            root_run_id,
        )
        started_event = HarnessEvent(
            type="run.started",
            agent_name=spec.name,
            thread_id=thread_id,
            run_id=root_run_id,
            parent_run_id=parent_run_id,
        )
        self._record_event(started_event)
        yield started_event
        for diagnostic in diagnostics:
            diagnostic_event = HarnessEvent(
                "action_space.selected",
                spec.name,
                thread_id,
                root_run_id,
                diagnostic,
            )
            self._record_event(diagnostic_event)
            yield diagnostic_event
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
                        self._record_event(replace(normalized, parent_run_id=root_run_id))
                        yield normalized
        except Exception as exc:
            logger.error(
                "run.failed agent=%s thread_id=%s run_id=%s error_type=%s",
                agent_name,
                thread_id,
                root_run_id,
                type(exc).__name__,
            )
            failed_event = HarnessEvent(
                type="run.failed",
                agent_name=spec.name,
                thread_id=thread_id,
                run_id=root_run_id,
                data={"error_type": type(exc).__name__, "message": str(exc)},
            )
            self._record_event(failed_event)
            yield failed_event
            raise
        completed_event = HarnessEvent(
            type="run.completed",
            agent_name=spec.name,
            thread_id=thread_id,
            run_id=root_run_id,
        )
        self._record_event(completed_event)
        yield completed_event
        logger.info(
            "run.completed agent=%s thread_id=%s run_id=%s mode=events",
            agent_name,
            thread_id,
            root_run_id,
        )

    def _spec(self, name: str) -> AgentSpec:
        try:
            return self._agents[name]
        except KeyError as exc:
            raise UnknownAgentError(f"unknown agent: {name}") from exc

    def _graph(self, spec: AgentSpec) -> tuple[Any, tuple[str, ...], tuple[Mapping[str, Any], ...]]:
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
                repr(self._tool_policies),
            )
        )
        if cached is not None and cached[0] == cache_key:
            logger.debug("graph.cache_hit agent=%s", spec.name)
            return cached[1], assembly.enabled_capabilities, assembly.diagnostics
        logger.debug(
            "graph.compile agent=%s tools=%d middleware=%d capabilities=%s",
            spec.name,
            len(assembly.tools),
            len(assembly.middleware),
            assembly.enabled_capabilities,
        )
        has_memory = "memory" in assembly.enabled_capabilities
        graph = create_agent(
            model=model,
            tools=list(assembly.tools),
            system_prompt=assembly.system_prompt,
            middleware=[
                *assembly.middleware,
                ToolExecutionMiddleware(
                    policies=self._tool_policies,
                    recorder=self._tool_recorder,
                    security_policy=self._security_policy,
                    tool_categories={
                        tool.name: getattr(tool, "category", "core") for tool in assembly.tools
                    },
                    approval_service=self._approval_service,
                ),
            ],
            response_format=spec.response_format,
            context_schema=RunContext,
            checkpointer=self._checkpointer if has_memory else None,
            store=self.memory.native_store if has_memory else None,
            name=spec.name,
        )
        self._compiled[spec.name] = (cache_key, graph)
        return graph, assembly.enabled_capabilities, assembly.diagnostics

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
        if spec.recursion_limit is not None:
            config["recursion_limit"] = spec.recursion_limit
        return config

    @staticmethod
    def _result(
        spec: AgentSpec,
        thread_id: str,
        state: Mapping[str, Any],
        *,
        run_id: str = "",
    ) -> RunResult:
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
            run_id=run_id,
            structured_response=state.get("structured_response"),
            model_provider=model_provider,
            model_name=model_name,
            usage_metadata=usage_metadata,
            response_metadata=response_metadata,
        )

    def _record_event(self, event: HarnessEvent) -> None:
        self._journal.append(event)


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


def _capability_check(name: str, required: bool, supported: bool | None) -> CapabilityCheck:
    status: CapabilityStatus
    if not required:
        status = "not_required"
        message = f"{name} is not required by this Agent."
    elif supported is False:
        status = "unsupported"
        message = f"The selected model does not support {name}."
    elif supported is True:
        status = "satisfied"
        message = f"The selected model supports {name}."
    else:
        status = "unknown"
        message = f"The selected model capability for {name} is unknown; run a live probe."
    return CapabilityCheck(
        name=name,
        required=required,
        supported=supported,
        status=status,
        message=message,
    )


def _category_checks(config: MosaicConfig) -> tuple[CategoryCheck, ...]:
    checks: list[CategoryCheck] = []
    if config.network.enabled:
        provider_available = config.network.provider != "ddgs" or find_spec("ddgs") is not None
        if provider_available:
            checks.append(
                CategoryCheck(
                    category="network",
                    enabled=True,
                    status="enabled",
                    message=(
                        f"network category is enabled with provider '{config.network.provider}'."
                    ),
                )
            )
        else:
            checks.append(
                CategoryCheck(
                    category="network",
                    enabled=True,
                    status="misconfigured",
                    message="Install the 'ddgs' package or configure another network provider.",
                )
            )
    else:
        checks.append(
            CategoryCheck(
                category="network",
                enabled=False,
                status="disabled",
                message="network category is disabled; network built-ins are unavailable.",
            )
        )

    filesystem_ready = config.filesystem.enabled and bool(config.filesystem.roots)
    checks.append(
        CategoryCheck(
            category="filesystem",
            enabled=config.filesystem.enabled,
            status=("enabled" if filesystem_ready else "misconfigured")
            if config.filesystem.enabled
            else "disabled",
            message=(
                "filesystem category is enabled with configured roots."
                if filesystem_ready
                else "Configure MOSAIC_FILESYSTEM_ROOTS before enabling filesystem tools."
                if config.filesystem.enabled
                else "filesystem category is disabled; filesystem built-ins are unavailable."
            ),
        )
    )

    documents_ready = config.documents.enabled and filesystem_ready
    checks.append(
        CategoryCheck(
            category="documents",
            enabled=config.documents.enabled,
            status=("enabled" if documents_ready else "misconfigured")
            if config.documents.enabled
            else "disabled",
            message=(
                "documents category is enabled with filesystem roots."
                if documents_ready
                else "Enable filesystem and configure roots before enabling document tools."
                if config.documents.enabled
                else "documents category is disabled; document built-ins are unavailable."
            ),
        )
    )
    return tuple(checks)


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
    elif event_type == "model.completed" and isinstance(data, Mapping):
        output = data.get("output")
        usage = getattr(output, "usage_metadata", None)
        if isinstance(usage, Mapping):
            safe_data["usage"] = _json_safe(dict(usage))
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
