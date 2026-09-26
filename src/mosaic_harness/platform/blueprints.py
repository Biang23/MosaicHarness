from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from ..core.models import ModelCapabilities, ModelSpec

if TYPE_CHECKING:
    from ..core.models import AgentSpec

BlueprintStatus = Literal["draft", "published"]
_SLUG = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
_SECRET_KEY = re.compile(
    r"(?:^|_)(?:api[_-]?key|access[_-]?token|auth(?:orization)?|credential|password|secret|token)(?:$|_)",
    re.IGNORECASE,
)
_MODEL_CONFIG_KEYS = frozenset(
    {
        "base_url",
        "api_key_env",
        "default_headers",
        "temperature",
        "max_tokens",
        "timeout",
        "max_retries",
        "params",
        "capabilities",
    }
)
_OMIT = object()


def _is_secret_key(key: object) -> bool:
    if not isinstance(key, str):
        return False
    normalized = key.lower()
    if normalized.endswith(("_env", "_ref")):
        return False
    return bool(_SECRET_KEY.search(normalized))


def _json_safe(value: Any, *, key: object | None = None) -> Any:
    """Convert declarative values to JSON data while omitting credential material."""
    if _is_secret_key(key):
        return _OMIT
    if isinstance(value, (ModelSpec, ModelCapabilities)):
        value = asdict(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for item_key, item_value in value.items():
            safe_value = _json_safe(item_value, key=item_key)
            if safe_value is not _OMIT:
                result[str(item_key)] = safe_value
        return result
    if isinstance(value, (tuple, list)):
        result_list: list[Any] = []
        for item in value:
            safe_value = _json_safe(item)
            if safe_value is not _OMIT:
                result_list.append(safe_value)
        return result_list
    raise TypeError(f"value of type {type(value).__name__} is not JSON serializable")


def _model_from_ref(
    value: str | Mapping[str, Any] | ModelSpec | None,
    *,
    coerce_mapping: bool = False,
) -> str | Mapping[str, Any] | ModelSpec | None:
    if value is None or isinstance(value, (str, ModelSpec)):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("model_ref must be a string, mapping, ModelSpec, or None")
    model_data = dict(value)
    if not coerce_mapping and not _MODEL_CONFIG_KEYS.intersection(model_data):
        return model_data
    capabilities = model_data.get("capabilities")
    if isinstance(capabilities, Mapping):
        model_data["capabilities"] = ModelCapabilities(**dict(capabilities))
    return ModelSpec(**model_data)


def _model_to_dict(value: str | Mapping[str, Any] | ModelSpec | None) -> Any:
    return _json_safe(value)


@dataclass(frozen=True, slots=True)
class AgentBlueprint:
    """Product-layer agent definition independent from the runtime harness."""

    slug: str
    display_name: str
    system_prompt: str
    id: str = ""
    icon: str = "agent"
    pixel_theme: str = "mosaic"
    template_id: str = "blank"
    model_ref: str | Mapping[str, Any] | ModelSpec | None = None
    tool_refs: tuple[str, ...] = ()
    skill_refs: tuple[str, ...] = ()
    memory_policy: Mapping[str, Any] = field(default_factory=dict)
    security_policy: Mapping[str, Any] = field(default_factory=dict)
    connector_refs: tuple[str, ...] = ()
    evaluation_suite: Mapping[str, Any] = field(default_factory=dict)
    status: BlueprintStatus = "draft"
    version: int = 0
    changelog: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _SLUG.fullmatch(self.slug):
            raise ValueError("slug must match ^[a-z][a-z0-9_-]{1,63}$")
        if not self.display_name.strip():
            raise ValueError("display_name must not be empty")
        if not self.system_prompt.strip():
            raise ValueError("system_prompt must not be empty")
        if self.status not in {"draft", "published"}:
            raise ValueError("status must be 'draft' or 'published'")
        if self.version < 0:
            raise ValueError("version must be non-negative")
        if not isinstance(self.model_ref, (str, Mapping, ModelSpec, type(None))):
            raise TypeError("model_ref must be a string, mapping, ModelSpec, or None")
        object.__setattr__(self, "id", self.id or f"bp_{uuid4().hex}")
        object.__setattr__(self, "tool_refs", tuple(self.tool_refs))
        object.__setattr__(self, "skill_refs", tuple(self.skill_refs))
        object.__setattr__(self, "connector_refs", tuple(self.connector_refs))
        object.__setattr__(self, "memory_policy", dict(self.memory_policy))
        object.__setattr__(self, "security_policy", dict(self.security_policy))
        object.__setattr__(self, "evaluation_suite", dict(self.evaluation_suite))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_agent_spec(self) -> AgentSpec:
        """Build the runtime SDK object at the explicit integration boundary."""
        from ..core.models import AgentSpec

        model = _model_from_ref(self.model_ref, coerce_mapping=True)
        if isinstance(model, Mapping):
            model = ModelSpec(**dict(model))
        memory_namespace = self.memory_policy.get("namespace")
        if not isinstance(memory_namespace, str) or not memory_namespace.strip():
            memory_namespace = self.slug
        runtime_metadata = dict(_json_safe(self.metadata))
        runtime_metadata.update(
            {
                "blueprint_id": self.id,
                "template_id": self.template_id,
                "skill_refs": tuple(self.skill_refs),
                "connector_refs": tuple(self.connector_refs),
                "security_policy": _json_safe(self.security_policy),
                "evaluation_suite": _json_safe(self.evaluation_suite),
            }
        )
        return AgentSpec(
            name=self.slug,
            description=self.display_name,
            system_prompt=self.system_prompt,
            model=model,
            tool_names=self.tool_refs,
            memory_namespace=memory_namespace,
            metadata=runtime_metadata,
        )

    @property
    def fingerprint(self) -> str:
        payload = self.to_dict()
        for key in ("id", "status", "version", "changelog"):
            payload.pop(key, None)
        return _fingerprint(payload)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "id": self.id,
            "slug": self.slug,
            "display_name": self.display_name,
            "icon": self.icon,
            "pixel_theme": self.pixel_theme,
            "template_id": self.template_id,
            "system_prompt": self.system_prompt,
            "model_ref": _model_to_dict(self.model_ref),
            "tool_refs": self.tool_refs,
            "skill_refs": self.skill_refs,
            "memory_policy": self.memory_policy,
            "security_policy": self.security_policy,
            "connector_refs": self.connector_refs,
            "evaluation_suite": self.evaluation_suite,
            "status": self.status,
            "version": self.version,
            "changelog": self.changelog,
            "metadata": self.metadata,
        }
        safe = _json_safe(data)
        assert isinstance(safe, dict)
        return safe

    def to_json(self, *, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=True, sort_keys=True, indent=indent)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AgentBlueprint:
        values = dict(data)
        values["model_ref"] = _model_from_ref(values.get("model_ref"))
        for field_name in ("tool_refs", "skill_refs", "connector_refs"):
            values[field_name] = tuple(values.get(field_name, ()))
        return cls(**values)

    @classmethod
    def from_json(cls, value: str) -> AgentBlueprint:
        parsed = json.loads(value)
        if not isinstance(parsed, Mapping):
            raise ValueError("blueprint JSON must contain an object")
        return cls.from_dict(parsed)


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class ReleaseManifest:
    """Immutable, JSON-safe snapshot of a published AgentBlueprint."""

    blueprint_id: str
    slug: str
    display_name: str
    system_prompt: str
    version: int
    fingerprint: str = ""
    release_id: str = ""
    icon: str = "agent"
    pixel_theme: str = "mosaic"
    template_id: str = "blank"
    model_ref: str | Mapping[str, Any] | ModelSpec | None = None
    tool_refs: tuple[str, ...] = ()
    skill_refs: tuple[str, ...] = ()
    memory_policy: Mapping[str, Any] = field(default_factory=dict)
    security_policy: Mapping[str, Any] = field(default_factory=dict)
    connector_refs: tuple[str, ...] = ()
    evaluation_suite: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    changelog: str = ""
    published_at: str = field(default_factory=_timestamp)

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("release version must be positive")
        object.__setattr__(self, "release_id", self.release_id or f"rel_{uuid4().hex}")
        if not self.fingerprint:
            object.__setattr__(self, "fingerprint", _release_fingerprint(self))
        object.__setattr__(self, "tool_refs", tuple(self.tool_refs))
        object.__setattr__(self, "skill_refs", tuple(self.skill_refs))
        object.__setattr__(self, "connector_refs", tuple(self.connector_refs))
        object.__setattr__(self, "memory_policy", dict(self.memory_policy))
        object.__setattr__(self, "security_policy", dict(self.security_policy))
        object.__setattr__(self, "evaluation_suite", dict(self.evaluation_suite))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @classmethod
    def from_blueprint(
        cls, blueprint: AgentBlueprint, *, version: int | None = None, changelog: str | None = None
    ) -> ReleaseManifest:
        return cls(
            blueprint_id=blueprint.id,
            slug=blueprint.slug,
            display_name=blueprint.display_name,
            system_prompt=blueprint.system_prompt,
            version=version if version is not None else max(1, blueprint.version),
            fingerprint=blueprint.fingerprint,
            icon=blueprint.icon,
            pixel_theme=blueprint.pixel_theme,
            template_id=blueprint.template_id,
            model_ref=blueprint.model_ref,
            tool_refs=blueprint.tool_refs,
            skill_refs=blueprint.skill_refs,
            memory_policy=blueprint.memory_policy,
            security_policy=blueprint.security_policy,
            connector_refs=blueprint.connector_refs,
            evaluation_suite=blueprint.evaluation_suite,
            metadata=blueprint.metadata,
            changelog=blueprint.changelog if changelog is None else changelog,
        )

    def to_blueprint(self, *, status: BlueprintStatus = "draft") -> AgentBlueprint:
        return AgentBlueprint(
            id=self.blueprint_id,
            slug=self.slug,
            display_name=self.display_name,
            system_prompt=self.system_prompt,
            icon=self.icon,
            pixel_theme=self.pixel_theme,
            template_id=self.template_id,
            model_ref=self.model_ref,
            tool_refs=self.tool_refs,
            skill_refs=self.skill_refs,
            memory_policy=self.memory_policy,
            security_policy=self.security_policy,
            connector_refs=self.connector_refs,
            evaluation_suite=self.evaluation_suite,
            metadata=self.metadata,
            status=status,
            version=self.version,
            changelog=self.changelog,
        )

    def to_agent_spec(self) -> AgentSpec:
        return self.to_blueprint(status="published").to_agent_spec()

    def to_dict(self) -> dict[str, Any]:
        data = {
            "release_id": self.release_id,
            "blueprint_id": self.blueprint_id,
            "slug": self.slug,
            "display_name": self.display_name,
            "icon": self.icon,
            "pixel_theme": self.pixel_theme,
            "template_id": self.template_id,
            "system_prompt": self.system_prompt,
            "model_ref": _model_to_dict(self.model_ref),
            "tool_refs": self.tool_refs,
            "skill_refs": self.skill_refs,
            "memory_policy": self.memory_policy,
            "security_policy": self.security_policy,
            "connector_refs": self.connector_refs,
            "evaluation_suite": self.evaluation_suite,
            "metadata": self.metadata,
            "version": self.version,
            "fingerprint": self.fingerprint,
            "changelog": self.changelog,
            "published_at": self.published_at,
        }
        safe = _json_safe(data)
        assert isinstance(safe, dict)
        return safe

    def to_json(self, *, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=True, sort_keys=True, indent=indent)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ReleaseManifest:
        values = dict(data)
        values["model_ref"] = _model_from_ref(values.get("model_ref"))
        for field_name in ("tool_refs", "skill_refs", "connector_refs"):
            values[field_name] = tuple(values.get(field_name, ()))
        return cls(**values)

    @classmethod
    def from_json(cls, value: str) -> ReleaseManifest:
        parsed = json.loads(value)
        if not isinstance(parsed, Mapping):
            raise ValueError("release JSON must contain an object")
        return cls.from_dict(parsed)


def _fingerprint(value: Mapping[str, Any]) -> str:
    canonical = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _release_fingerprint(release: ReleaseManifest) -> str:
    return _fingerprint(
        {
            "blueprint_id": release.blueprint_id,
            "slug": release.slug,
            "display_name": release.display_name,
            "system_prompt": release.system_prompt,
            "icon": release.icon,
            "pixel_theme": release.pixel_theme,
            "template_id": release.template_id,
            "model_ref": _model_to_dict(release.model_ref),
            "tool_refs": release.tool_refs,
            "skill_refs": release.skill_refs,
            "memory_policy": release.memory_policy,
            "security_policy": release.security_policy,
            "connector_refs": release.connector_refs,
            "evaluation_suite": release.evaluation_suite,
            "metadata": release.metadata,
        }
    )
