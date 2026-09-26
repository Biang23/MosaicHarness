from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

ResourceKind = Literal["model", "tool", "skill", "capability", "connector"]
RiskLevel = Literal["low", "medium", "high", "critical"]

_SECRET_KEYS = {
    "api_key",
    "authorization",
    "credential",
    "credential_ref",
    "password",
    "secret",
    "token",
}


def _assert_safe_json(value: Any, *, path: str = "metadata") -> Any:
    """Reject secret-bearing keys before a descriptor can cross the control-plane boundary."""

    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if normalized in _SECRET_KEYS or any(
                marker in normalized for marker in ("api_key", "access_token", "secret")
            ):
                raise ValueError(f"{path} contains a sensitive field: {key}")
            _assert_safe_json(nested, path=f"{path}.{key}")
        return value
    if isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _assert_safe_json(nested, path=f"{path}[{index}]")
        return value
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError(f"{path} must contain JSON-safe values")


class ResourceDescriptor(BaseModel):
    """A JSON-safe description of a platform resource.

    This is deliberately independent from runtime objects such as LangChain tools,
    model instances, or MosaicHarness capabilities.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=128)
    kind: ResourceKind
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    required_capabilities: tuple[str, ...] = ()
    risk_level: RiskLevel = "low"
    requires_credentials: bool = False
    supported: bool = True
    requires_approval: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata", mode="before")
    @classmethod
    def _validate_metadata(cls, value: Any) -> dict[str, Any]:
        _assert_safe_json(value)
        return dict(value or {})

    @field_validator("input_schema", "output_schema", mode="before")
    @classmethod
    def _validate_schema(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("schema must be a JSON object")
        _assert_safe_json(value, path="schema")
        return dict(value)

    @field_validator("required_capabilities", mode="before")
    @classmethod
    def _normalize_capabilities(cls, value: Any) -> tuple[str, ...]:
        return tuple(str(item) for item in (value or ()))


class DescriptorSource(Protocol):
    def resource_descriptors(self) -> Iterable[ResourceDescriptor]: ...


class ResourceCatalog:
    """Kind-aware in-memory resource catalog owned by the control plane."""

    def __init__(
        self,
        descriptors: Iterable[ResourceDescriptor] = (),
        *,
        sources: Iterable[DescriptorSource] = (),
    ) -> None:
        self._items: dict[tuple[ResourceKind, str], ResourceDescriptor] = {}
        self.register_many(descriptors)
        for source in sources:
            self.register_many(source.resource_descriptors())

    def register(self, descriptor: ResourceDescriptor) -> ResourceDescriptor:
        key = (descriptor.kind, descriptor.id)
        if key in self._items:
            raise ValueError(f"resource already registered: {descriptor.kind}:{descriptor.id}")
        self._items[key] = descriptor
        return descriptor

    def register_many(
        self,
        descriptors: Iterable[ResourceDescriptor],
    ) -> tuple[ResourceDescriptor, ...]:
        incoming = tuple(descriptors)
        keys = [(item.kind, item.id) for item in incoming]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate resources in batch")
        conflicts = set(keys).intersection(self._items)
        if conflicts:
            formatted = ", ".join(f"{kind}:{resource_id}" for kind, resource_id in conflicts)
            raise ValueError(f"resources already registered: {formatted}")
        self._items.update(zip(keys, incoming, strict=True))
        return incoming

    def get(self, resource_id: str, *, kind: ResourceKind | None = None) -> ResourceDescriptor:
        if kind is not None:
            try:
                return self._items[(kind, resource_id)]
            except KeyError as exc:
                raise KeyError(f"unknown resource: {kind}:{resource_id}") from exc
        matches = [item for (_, item_id), item in self._items.items() if item_id == resource_id]
        if not matches:
            raise KeyError(f"unknown resource: {resource_id}")
        if len(matches) > 1:
            raise ValueError(f"resource id is ambiguous across kinds: {resource_id}")
        return matches[0]

    def list(
        self,
        *,
        kind: ResourceKind | None = None,
        include_unsupported: bool = True,
    ) -> tuple[ResourceDescriptor, ...]:
        return tuple(
            item
            for item in self._items.values()
            if (kind is None or item.kind == kind) and (include_unsupported or item.supported)
        )

    def discover(
        self,
        query: str = "",
        *,
        kind: ResourceKind | None = None,
        limit: int = 50,
        include_unsupported: bool = True,
    ) -> tuple[ResourceDescriptor, ...]:
        if limit < 1:
            raise ValueError("limit must be positive")
        lowered = query.casefold().strip()
        matches = []
        for item in self.list(kind=kind, include_unsupported=include_unsupported):
            haystack = f"{item.id} {item.name} {item.description}".casefold()
            if not lowered or lowered in haystack:
                matches.append(item)
        return tuple(matches[:limit])

    def describe(self, *, kind: ResourceKind | None = None) -> tuple[dict[str, Any], ...]:
        return tuple(item.model_dump(mode="json") for item in self.list(kind=kind))


def _schema_from_tool(tool: Any) -> dict[str, Any]:
    args_schema = getattr(tool, "args_schema", None)
    if args_schema is not None and hasattr(args_schema, "model_json_schema"):
        return dict(args_schema.model_json_schema())
    args = getattr(tool, "args", None)
    return dict(args) if isinstance(args, Mapping) else {}


def _tool_descriptor(tool: Any) -> ResourceDescriptor:
    name = str(getattr(tool, "name", "")).strip()
    if not name:
        raise ValueError("tool registry item must have a name")
    return ResourceDescriptor(
        id=name,
        kind="tool",
        name=name,
        description=str(getattr(tool, "description", "") or ""),
        input_schema=_schema_from_tool(tool),
        required_capabilities=tuple(getattr(tool, "required_capabilities", ()) or ()),
        risk_level=getattr(tool, "risk_level", "low"),
        requires_credentials=bool(getattr(tool, "requires_credentials", False)),
        requires_approval=bool(getattr(tool, "requires_approval", False)),
        metadata={"source": "tool_registry"},
    )


def descriptors_from_tool_registry(registry: Any) -> tuple[ResourceDescriptor, ...]:
    """Adapt a ToolRegistry-like object without retaining or exposing tool objects."""

    if hasattr(registry, "names") and hasattr(registry, "resolve"):
        names = tuple(registry.names)
        return tuple(_tool_descriptor(tool) for tool in registry.resolve(names))
    if hasattr(registry, "search"):
        results = registry.search("", limit=10_000)
        return tuple(
            ResourceDescriptor(
                id=str(item["name"]),
                kind="tool",
                name=str(item["name"]),
                description=str(item.get("description", "")),
                metadata={"source": "tool_registry"},
            )
            for item in results
        )
    raise TypeError("registry must provide names/resolve or search")


def descriptors_from_skill_registry(registry: Any) -> tuple[ResourceDescriptor, ...]:
    """Adapt a SkillRegistry-like object into safe descriptors."""

    skills = getattr(registry, "skills", None)
    if skills is None:
        raise TypeError("registry must provide a skills collection")
    return tuple(
        ResourceDescriptor(
            id=str(skill.name),
            kind="skill",
            name=str(skill.name),
            description=str(getattr(skill, "description", "") or ""),
            metadata={"source": "skill_registry"},
        )
        for skill in skills
    )


def descriptors_from_model_registry(registry: Any) -> tuple[ResourceDescriptor, ...]:
    """Expose provider metadata without resolving models or importing optional SDKs."""

    registry = getattr(registry, "registry", registry)
    names = tuple(getattr(registry, "names", ()))
    providers: dict[str, Any] = {}
    for name in names:
        provider = registry.get(name) if hasattr(registry, "get") else None
        canonical = str(getattr(provider, "name", name))
        providers[canonical] = provider

    descriptors = []
    for name, provider in providers.items():
        credential_env = getattr(provider, "credential_env", None)
        descriptors.append(
            ResourceDescriptor(
                id=name,
                kind="model",
                name=name,
                description=f"Model provider: {name}",
                requires_credentials=bool(credential_env),
                metadata={
                    "source": "model_registry",
                    "optional_dependency": getattr(provider, "optional_dependency", ""),
                    "install_extra": getattr(provider, "install_extra", ""),
                    "credential_env": credential_env or "",
                },
            )
        )
    return tuple(descriptors)


def descriptors_from_capabilities(capabilities: Iterable[Any]) -> tuple[ResourceDescriptor, ...]:
    descriptors = []
    for capability in capabilities:
        if isinstance(capability, str):
            name, description = capability, ""
        elif isinstance(capability, Mapping):
            name = str(capability["name"])
            description = str(capability.get("description", ""))
        else:
            name = str(capability.name)
            description = str(getattr(capability, "description", "") or "")
        descriptors.append(
            ResourceDescriptor(
                id=name,
                kind="capability",
                name=name,
                description=description,
                metadata={"source": "capability_registry"},
            )
        )
    return tuple(descriptors)
