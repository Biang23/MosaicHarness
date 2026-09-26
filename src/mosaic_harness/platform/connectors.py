from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .resources import ResourceDescriptor

_CONNECTOR_ID = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
_CREDENTIAL_REF = re.compile(r"^(env|keychain):[A-Za-z][A-Za-z0-9_.-]*$")
_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
RiskLevel = Literal["low", "medium", "high", "critical"]
_SENSITIVE_FIELD_MARKERS = ("api_key", "authorization", "password", "secret", "token")


class ConnectorSpec(BaseModel):
    """Declarative, controlled HTTP connector metadata.

    ConnectorSpec does not perform requests. A separate execution adapter must
    enforce allowlists, approval, timeout, retries, and credential resolution.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=2, max_length=64)
    display_name: str = ""
    description: str = ""
    url: str
    method: str = "GET"
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    allowed_domains: tuple[str, ...] = ()
    credential_ref: str | None = None
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    max_retries: int = Field(default=2, ge=0, le=10)
    read_only: bool | None = None
    risk_level: RiskLevel = "low"
    requires_approval: bool | None = None

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        if not _CONNECTOR_ID.fullmatch(value):
            raise ValueError("id must match ^[a-z][a-z0-9_-]{1,63}$")
        return value

    @field_validator("method")
    @classmethod
    def _normalize_method(cls, value: str) -> str:
        method = value.upper()
        if method not in _METHODS:
            raise ValueError(f"method must be one of: {', '.join(sorted(_METHODS))}")
        return method

    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("url must be an absolute http(s) URL")
        if parsed.username or parsed.password:
            raise ValueError("url must not contain userinfo")
        query_keys = {part.split("=", 1)[0].casefold() for part in parsed.query.split("&") if part}
        if any(
            any(marker in key.replace("-", "_") for marker in _SENSITIVE_FIELD_MARKERS)
            for key in query_keys
        ):
            raise ValueError("url must not contain sensitive query parameters")
        return value

    @field_validator("allowed_domains", mode="before")
    @classmethod
    def _normalize_domains(cls, value: object) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            value = (value,)
        if not isinstance(value, Iterable):
            raise ValueError("allowed_domains must be a sequence of host names")
        return tuple(str(item).casefold().strip(".") for item in value)

    @field_validator("credential_ref")
    @classmethod
    def _validate_credential_ref(cls, value: str | None) -> str | None:
        if value is not None and not _CREDENTIAL_REF.fullmatch(value):
            raise ValueError("credential_ref must be an env: or keychain: reference")
        return value

    @field_validator("input_schema", "output_schema", mode="before")
    @classmethod
    def _validate_schema(cls, value: object) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("schema must be a JSON object")

        def visit(node: object) -> None:
            if isinstance(node, Mapping):
                for key, nested in node.items():
                    normalized = str(key).casefold().replace("-", "_")
                    if any(marker in normalized for marker in _SENSITIVE_FIELD_MARKERS):
                        raise ValueError("schemas must not contain sensitive fields")
                    visit(nested)
            elif isinstance(node, (list, tuple)):
                for nested in node:
                    visit(nested)
            elif node is not None and not isinstance(node, (str, int, float, bool)):
                raise ValueError("schema must contain JSON-safe values")

        visit(value)
        return dict(value)

    @model_validator(mode="after")
    def _validate_policy(self) -> ConnectorSpec:
        host = self.host
        domains = self.allowed_domains or (host,)
        if not any(host == domain or host.endswith(f".{domain}") for domain in domains):
            raise ValueError("url host must be covered by allowed_domains")
        object.__setattr__(self, "allowed_domains", domains)

        inferred_read_only = self.method in _READ_METHODS
        if self.read_only is None:
            object.__setattr__(self, "read_only", inferred_read_only)
        elif self.read_only != inferred_read_only:
            raise ValueError("read_only must match the HTTP method's mutating behavior")
        if self.requires_approval is None:
            object.__setattr__(self, "requires_approval", not self.read_only)
        elif not self.read_only and not self.requires_approval:
            raise ValueError("mutating connectors require approval")
        return self

    @property
    def host(self) -> str:
        return str(urlparse(self.url).hostname).casefold()

    @property
    def requires_credentials(self) -> bool:
        return self.credential_ref is not None

    def to_descriptor(self) -> ResourceDescriptor:
        return ResourceDescriptor(
            id=self.id,
            kind="connector",
            name=self.display_name or self.id,
            description=self.description,
            input_schema=self.input_schema,
            output_schema=self.output_schema,
            required_capabilities=("network",),
            risk_level=self.risk_level,
            requires_credentials=self.requires_credentials,
            supported=True,
            requires_approval=bool(self.requires_approval),
            metadata={
                "method": self.method,
                "url": self.url,
                "allowed_domains": list(self.allowed_domains),
                "timeout_seconds": self.timeout_seconds,
                "max_retries": self.max_retries,
                "read_only": bool(self.read_only),
            },
        )

    def to_public_dict(self) -> dict[str, Any]:
        """Serialize connector metadata without exporting the credential reference."""

        return self.model_dump(mode="json", exclude={"credential_ref"})


class ConnectorRegistry:
    """Control-plane registry for connector declarations, never request execution."""

    def __init__(self, connectors: Iterable[ConnectorSpec] = ()) -> None:
        self._connectors: dict[str, ConnectorSpec] = {}
        for connector in connectors:
            self.register(connector)

    def register(self, connector: ConnectorSpec) -> ConnectorSpec:
        if connector.id in self._connectors:
            raise ValueError(f"connector already registered: {connector.id}")
        self._connectors[connector.id] = connector
        return connector

    def get(self, connector_id: str) -> ConnectorSpec:
        try:
            return self._connectors[connector_id]
        except KeyError as exc:
            raise KeyError(f"unknown connector: {connector_id}") from exc

    def list(self) -> tuple[ConnectorSpec, ...]:
        return tuple(self._connectors.values())

    def descriptors(self) -> tuple[ResourceDescriptor, ...]:
        return tuple(connector.to_descriptor() for connector in self._connectors.values())

    def describe(self) -> tuple[dict[str, Any], ...]:
        return tuple(connector.to_public_dict() for connector in self._connectors.values())
