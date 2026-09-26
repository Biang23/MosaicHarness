from __future__ import annotations

import pytest
from pydantic import ValidationError

from mosaic_harness.platform.connectors import ConnectorRegistry, ConnectorSpec


def test_connector_spec_validates_and_exposes_safe_resource_metadata() -> None:
    connector = ConnectorSpec(
        id="weather",
        display_name="Weather API",
        url="https://api.example.test/weather",
        method="GET",
        input_schema={"type": "object", "properties": {"city": {"type": "string"}}},
        output_schema={"type": "object"},
        allowed_domains=("api.example.test",),
        credential_ref="env:WEATHER_API_KEY",
        read_only=True,
        risk_level="low",
    )

    assert connector.host == "api.example.test"
    assert connector.requires_credentials is True
    assert connector.to_descriptor().model_dump(mode="json") == {
        "id": "weather",
        "kind": "connector",
        "name": "Weather API",
        "description": "",
        "input_schema": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
        },
        "output_schema": {"type": "object"},
        "required_capabilities": ["network"],
        "risk_level": "low",
        "requires_credentials": True,
        "supported": True,
        "requires_approval": False,
        "metadata": {
            "method": "GET",
            "url": "https://api.example.test/weather",
            "allowed_domains": ["api.example.test"],
            "timeout_seconds": 30.0,
            "max_retries": 2,
            "read_only": True,
        },
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("url", "file:///tmp/secrets"),
        ("method", "TRACE"),
        ("timeout_seconds", 0),
        ("max_retries", -1),
        ("credential_ref", "sk-live-secret-value"),
    ],
)
def test_connector_spec_rejects_unsafe_or_invalid_values(field: str, value: object) -> None:
    values = {
        "id": "unsafe",
        "url": "https://api.example.test/run",
        "allowed_domains": ("api.example.test",),
    }
    values[field] = value

    with pytest.raises(ValidationError):
        ConnectorSpec(**values)


def test_write_connector_requires_confirmation_and_cannot_claim_read_only() -> None:
    with pytest.raises(ValidationError, match="read_only"):
        ConnectorSpec(
            id="write",
            url="https://api.example.test/items",
            method="POST",
            allowed_domains=("api.example.test",),
            read_only=True,
        )

    connector = ConnectorSpec(
        id="write",
        url="https://api.example.test/items",
        method="POST",
        allowed_domains=("api.example.test",),
        read_only=False,
    )

    assert connector.requires_approval is True


def test_connector_registry_rejects_duplicate_ids_and_lists_json_safe_specs() -> None:
    registry = ConnectorRegistry()
    connector = ConnectorSpec(
        id="weather",
        url="https://api.example.test/weather",
        allowed_domains=("api.example.test",),
    )

    registry.register(connector)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(connector)

    assert registry.get("weather") == connector
    assert registry.list()[0].id == "weather"
    assert "credential_ref" not in registry.describe()[0]
