from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import suppress
from dataclasses import asdict
from typing import Any, Protocol

from ..core.models import HarnessEvent, RunContext
from .blueprints import AgentBlueprint, ReleaseManifest
from .connectors import ConnectorRegistry, ConnectorSpec
from .evaluation import EvaluationGate, EvaluationSummary
from .repositories import BlueprintNotFoundError, BlueprintRepository
from .resources import (
    ResourceCatalog,
    descriptors_from_tool_registry,
)
from .runtime import HarnessRuntimeAdapter, PreviewResult
from .templates import TemplateCatalog, built_in_templates


class RuntimeAdapter(Protocol):
    """Minimal runtime contract consumed by the independent control plane."""

    tools: Any
    capabilities: Any
    agent_names: tuple[str, ...]
    journal: Any

    def define(self, spec: Any) -> Any: ...

    def invoke(
        self,
        agent_name: str,
        prompt: str,
        *,
        context: RunContext,
        thread_id: str,
    ) -> Any: ...

    def preview(
        self,
        spec: Any,
        *,
        prompt: str,
        context: RunContext,
        thread_id: str,
    ) -> PreviewResult: ...

    def stream(
        self,
        agent_name: str,
        prompt: str,
        *,
        context: RunContext,
        thread_id: str,
    ) -> AsyncIterator[str]: ...


class MosaicPlatform:
    """Local-first control-plane service built around public harness contracts.

    The service owns blueprints, releases, resources, and connector declarations.
    It only calls the runtime's public ``define``, ``invoke``, ``manifest``, and
    ``journal`` APIs; it never stores platform state inside ``MosaicHarness``.
    """

    def __init__(
        self,
        runtime: Any,
        *,
        repository: BlueprintRepository | None = None,
        catalog: ResourceCatalog | None = None,
        connectors: ConnectorRegistry | None = None,
        templates: TemplateCatalog | None = None,
    ) -> None:
        self.runtime = runtime if hasattr(runtime, "preview") else HarnessRuntimeAdapter(runtime)
        if repository is None:
            from .repositories import InMemoryBlueprintRepository

            repository = InMemoryBlueprintRepository()
        self.repository = repository
        self.connectors = connectors or ConnectorRegistry()
        self.templates = templates or TemplateCatalog(built_in_templates())
        if catalog is None:
            descriptors = descriptors_from_tool_registry(self.runtime.tools)
            catalog = ResourceCatalog(descriptors)
        self.catalog = catalog
        for descriptor in self.connectors.descriptors():
            with suppress(ValueError):
                self.catalog.register(descriptor)

    def list_blueprints(self) -> tuple[AgentBlueprint, ...]:
        return self.repository.list()

    def list_templates(self) -> tuple[Any, ...]:
        return self.templates.list()

    def get_blueprint(self, blueprint_id: str) -> AgentBlueprint:
        return self.repository.get(blueprint_id)

    def create_blueprint(self, payload: AgentBlueprint | Mapping[str, Any]) -> AgentBlueprint:
        blueprint = (
            payload if isinstance(payload, AgentBlueprint) else AgentBlueprint.from_dict(payload)
        )
        return self.repository.create(blueprint)

    def update_blueprint(
        self,
        blueprint_id: str,
        payload: AgentBlueprint | Mapping[str, Any],
    ) -> AgentBlueprint:
        if isinstance(payload, AgentBlueprint):
            return self.repository.update(blueprint_id, payload)
        return self.repository.update(blueprint_id, **dict(payload))

    def validate_blueprint(self, blueprint_id: str) -> dict[str, Any]:
        blueprint = self.get_blueprint(blueprint_id)
        errors: list[str] = []
        warnings: list[str] = []
        if blueprint.model_ref is None:
            errors.append("model_ref is required")

        known_tools = set(self.runtime.tools.names)
        for name in blueprint.tool_refs:
            if name not in known_tools:
                errors.append(f"unknown tool: {name}")
        for connector_id in blueprint.connector_refs:
            try:
                self.connectors.get(connector_id)
            except KeyError:
                errors.append(f"unknown connector: {connector_id}")

        try:
            spec = blueprint.to_agent_spec()
            self.runtime.capabilities.validate(spec)
        except Exception as exc:
            errors.append(f"runtime validation failed: {type(exc).__name__}: {exc}")

        try:
            gate = EvaluationGate.from_mapping(dict(blueprint.evaluation_suite))
            report = blueprint.evaluation_suite.get("last_report")
            summary = (
                EvaluationSummary(
                    dataset_version=str(report["dataset_version"]),
                    pass_rate=float(report["pass_rate"]),
                    evaluator_scores={
                        str(key): float(value)
                        for key, value in dict(report.get("evaluator_scores", {})).items()
                    },
                )
                if isinstance(report, Mapping)
                else None
            )
            evaluation = gate.check(summary)
            errors.extend(evaluation.errors)
            warnings.extend(evaluation.warnings)
        except (TypeError, ValueError, KeyError) as exc:
            errors.append(f"evaluation validation failed: {exc}")

        if blueprint.status == "published":
            warnings.append("published blueprints are immutable until a new release is created")
        return {
            "ok": not errors,
            "blueprint_id": blueprint.id,
            "errors": errors,
            "warnings": warnings,
            "runtime_agent_defined": blueprint.slug in self.runtime.agent_names,
        }

    def evaluate_blueprint(
        self,
        blueprint_id: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        blueprint = self.get_blueprint(blueprint_id)
        summary = EvaluationSummary(
            dataset_version=str(payload.get("dataset_version", "")),
            pass_rate=float(payload.get("pass_rate", -1)),
            evaluator_scores={
                str(key): float(value)
                for key, value in dict(payload.get("evaluator_scores", {})).items()
            },
        )
        gate = EvaluationGate.from_mapping(dict(blueprint.evaluation_suite))
        result = gate.check(summary)
        suite = dict(blueprint.evaluation_suite)
        suite["last_report"] = {
            "dataset_version": summary.dataset_version,
            "pass_rate": summary.pass_rate,
            "evaluator_scores": summary.evaluator_scores,
        }
        self.repository.update(blueprint_id, evaluation_suite=suite)
        return {
            "blueprint_id": blueprint_id,
            "ok": result.ok,
            "informational": result.informational,
            "errors": result.errors,
            "warnings": result.warnings,
        }

    def publish_blueprint(
        self,
        blueprint_id: str,
        payload: Mapping[str, Any] | None = None,
    ) -> ReleaseManifest:
        payload = payload or {}
        validation = self.validate_blueprint(blueprint_id)
        if not validation["ok"]:
            raise ValueError("blueprint failed validation: " + "; ".join(validation["errors"]))
        blueprint = self.get_blueprint(blueprint_id)
        latest = _latest_release(self.repository, blueprint.id)
        if (
            latest is not None
            and latest.fingerprint != blueprint.fingerprint
            and blueprint.slug in self.runtime.agent_names
        ):
            raise ValueError(
                "runtime agent is already defined; changed releases require a new runtime"
            )
        release = self.repository.publish(
            blueprint_id,
            changelog=str(payload.get("changelog", "")) or None,
        )
        if release.slug not in self.runtime.agent_names:
            self.runtime.define(release.to_agent_spec())
        return release

    def get_release(self, agent_name: str) -> ReleaseManifest:
        for blueprint in self.repository.list():
            if blueprint.slug == agent_name:
                return self.repository.get_release(blueprint.id)
        raise BlueprintNotFoundError(agent_name)

    def preview_blueprint(
        self,
        blueprint_id: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        blueprint = self.get_blueprint(blueprint_id)
        prompt = payload.get("input") or payload.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("'input' or 'prompt' is required")
        thread_id = str(payload.get("thread_id", payload.get("threadId", "preview")))
        user_id = str(payload.get("user_id", payload.get("userId", "local-user")))
        session_id = str(payload.get("session_id", payload.get("sessionId", thread_id)))
        result = self.runtime.preview(
            blueprint.to_agent_spec(),
            prompt=prompt,
            context=RunContext(user_id=user_id, session_id=session_id),
            thread_id=thread_id,
        )
        return {
            "run_id": result.run_id,
            "agent_name": result.agent_name,
            "thread_id": result.thread_id,
            "output_text": result.output_text,
            "structured_response": result.structured_response,
        }

    def get_run_events(self, blueprint_id: str, run_id: str) -> tuple[dict[str, Any], ...]:
        self.get_blueprint(blueprint_id)
        events = self.runtime.journal.events(run_id)
        if not events:
            raise KeyError(run_id)
        return tuple(_event_dict(event) for event in events)

    async def stream_blueprint(
        self,
        blueprint_id: str,
        payload: Mapping[str, Any],
    ) -> AsyncIterator[str]:
        blueprint = self.get_blueprint(blueprint_id)
        if blueprint.slug not in self.runtime.agent_names:
            raise ValueError("blueprint must be published before a live run")
        prompt = payload.get("input") or payload.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("'input' or 'prompt' is required")
        thread_id = str(payload.get("thread_id", payload.get("threadId", "run")))
        user_id = str(payload.get("user_id", payload.get("userId", "local-user")))
        session_id = str(payload.get("session_id", payload.get("sessionId", thread_id)))
        stream = getattr(self.runtime, "stream", None)
        if not callable(stream):
            raise NotImplementedError("runtime adapter does not support live event streams")
        async for frame in stream(
            blueprint.slug,
            prompt,
            context=RunContext(user_id=user_id, session_id=session_id),
            thread_id=thread_id,
        ):
            yield frame

    def list_resources(self, kind: str | None = None) -> tuple[dict[str, Any], ...]:
        return self.catalog.describe(kind=kind)  # type: ignore[arg-type]

    def list_connectors(self) -> tuple[dict[str, Any], ...]:
        return self.connectors.describe()

    def create_connector(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        connector = self.connectors.register(ConnectorSpec.model_validate(dict(payload)))
        descriptor = connector.to_descriptor()
        self.catalog.register(descriptor)
        return connector.model_dump(mode="json", exclude={"credential_ref"})


def _event_dict(event: HarnessEvent) -> dict[str, Any]:
    payload = asdict(event)
    payload["created_at"] = event.created_at.isoformat()
    return payload


def _latest_release(
    repository: BlueprintRepository,
    blueprint_id: str,
) -> ReleaseManifest | None:
    try:
        return repository.get_release(blueprint_id)
    except BlueprintNotFoundError:
        return None


__all__ = ["MosaicPlatform", "RuntimeAdapter"]
