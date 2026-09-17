from __future__ import annotations

from typing import Any, cast

import pytest

from mosaic_harness import ModelCapabilities, ModelSpec
from mosaic_harness.core.errors import MissingOptionalDependencyError
from mosaic_harness.models import ModelFactory

from .fakes import ScriptedChatModel


class FakeProvider:
    name = "fake"
    optional_dependency = "fake-provider"
    install_extra = "dev"

    def __init__(self) -> None:
        self.build_count = 0

    def build(self, spec: ModelSpec) -> ScriptedChatModel:
        self.build_count += 1
        return ScriptedChatModel()

    def describe(self, spec: ModelSpec) -> ModelCapabilities:
        del spec
        return ModelCapabilities(tool_calling=True, structured_output=True)


def test_factory_keeps_existing_chat_model_instances() -> None:
    model = ScriptedChatModel()

    assert ModelFactory().resolve(model) is model


def test_factory_registers_deepseek_kimi_and_qwen_providers() -> None:
    factory = ModelFactory()

    assert {"deepseek", "kimi", "moonshot", "qwen"}.issubset(set(factory.registry.names))


def test_deepseek_reasoner_declares_tool_calling_as_unsupported() -> None:
    capabilities = ModelFactory().describe(
        ModelSpec(provider="deepseek", model="deepseek-reasoner")
    )

    assert capabilities.tool_calling is False
    assert capabilities.structured_output is False
    assert capabilities.reasoning is True


def test_factory_builds_openai_compatible_model_with_custom_endpoint() -> None:
    pytest.importorskip("langchain_openai")
    model = ModelFactory().resolve(
        ModelSpec(
            provider="openai",
            model="qwen-local",
            base_url="http://127.0.0.1:8000/v1",
            api_key="local-key",
            params={"seed": 7},
        )
    )
    model = cast(Any, model)

    assert model.model_name == "qwen-local"
    assert str(model.openai_api_base) == "http://127.0.0.1:8000/v1"
    assert model.seed == 7
    assert model.use_responses_api is False


def test_factory_builds_deepseek_model() -> None:
    pytest.importorskip("langchain_deepseek")
    model = ModelFactory().resolve(
        ModelSpec(
            provider="deepseek",
            model="deepseek-chat",
            api_key="deepseek-key",
            max_tokens=256,
        )
    )
    model = cast(Any, model)

    assert model.model == "deepseek-chat"
    assert model.max_tokens == 256


def test_factory_builds_anthropic_model_with_current_constructor() -> None:
    pytest.importorskip("langchain_anthropic")
    model = ModelFactory().resolve(
        ModelSpec(
            provider="anthropic",
            model="claude-test",
            api_key="anthropic-key",
            max_tokens=256,
            base_url="https://anthropic.example/v1",
        )
    )
    model = cast(Any, model)

    assert model.model == "claude-test"
    assert model.max_tokens == 256
    assert model.anthropic_api_url == "https://anthropic.example/v1"


def test_factory_builds_kimi_model() -> None:
    pytest.importorskip("langchain_moonshot")
    model = ModelFactory().resolve(
        ModelSpec(
            provider="kimi",
            model="kimi-k2.5",
            api_key="moonshot-key",
            params={"thinking": False},
        )
    )
    model = cast(Any, model)

    assert model.model == "kimi-k2.5"
    assert model.thinking is False


def test_factory_builds_ollama_model_with_local_options() -> None:
    pytest.importorskip("langchain_ollama")
    model = ModelFactory().resolve(
        ModelSpec(
            provider="ollama",
            model="qwen3:8b",
            base_url="http://127.0.0.1:11434",
            max_tokens=128,
            timeout=5,
        )
    )
    model = cast(Any, model)

    assert model.model == "qwen3:8b"
    assert model.base_url == "http://127.0.0.1:11434"
    assert model.num_predict == 128
    assert model.client_kwargs["timeout"] == 5


def test_factory_builds_qwen_model() -> None:
    pytest.importorskip("langchain_qwq")
    model = ModelFactory().resolve(
        ModelSpec(
            provider="qwen",
            model="qwen-flash",
            api_key="dashscope-key",
            max_tokens=256,
        )
    )
    model = cast(Any, model)

    assert model.model == "qwen-flash"
    assert model.max_tokens == 256


def test_factory_reports_missing_optional_provider_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mosaic_harness.models.providers import anthropic as anthropic_provider

    def missing_dependency(name: str) -> None:
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(anthropic_provider, "import_module", missing_dependency)

    with pytest.raises(MissingOptionalDependencyError, match="langchain-anthropic"):
        ModelFactory().resolve(ModelSpec(provider="anthropic", model="claude-test"))


def test_factory_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="unknown model provider"):
        ModelFactory().resolve(ModelSpec(provider="unknown", model="model"))


def test_factory_allows_a_python_registered_provider() -> None:
    provider = FakeProvider()
    factory = ModelFactory()
    factory.register(provider)

    model = factory.resolve(ModelSpec(provider="fake", model="test"))

    assert isinstance(model, ScriptedChatModel)
    assert provider.build_count == 1
