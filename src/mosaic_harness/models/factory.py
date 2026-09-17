from __future__ import annotations

import hashlib

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from ..core.errors import MissingOptionalDependencyError, UnknownModelProviderError
from ..core.models import ModelCapabilities, ModelInput, ModelSpec
from .providers import (
    AnthropicProvider,
    DeepSeekProvider,
    MoonshotProvider,
    OllamaProvider,
    OpenAIProvider,
    QwenProvider,
)
from .registry import ModelProvider, ProviderRegistry


class ModelFactory:
    """Resolve user-facing model inputs into LangChain chat model instances."""

    def __init__(self, registry: ProviderRegistry | None = None) -> None:
        self.registry = registry or ProviderRegistry(
            [
                OpenAIProvider(),
                AnthropicProvider(),
                OllamaProvider(),
                DeepSeekProvider(),
                MoonshotProvider(),
                QwenProvider(),
            ]
        )

    def register(self, provider: ModelProvider) -> None:
        self.registry.register(provider)

    def resolve(self, model: ModelInput) -> BaseChatModel:
        if isinstance(model, BaseChatModel):
            return model
        if isinstance(model, str):
            try:
                return init_chat_model(model)
            except ImportError as exc:
                raise MissingOptionalDependencyError(
                    "model string requires its LangChain provider package; "
                    "install the corresponding Mosaic model extra"
                ) from exc
        provider = self.registry.get(model.provider)
        if provider is None:
            raise UnknownModelProviderError(f"unknown model provider: {model.provider}")
        try:
            return provider.build(model)
        except ImportError as exc:
            raise MissingOptionalDependencyError(
                f"provider '{model.provider}' requires {provider.optional_dependency}; "
                f"install with `uv sync --extra {provider.install_extra}`"
            ) from exc

    def describe(self, model: ModelInput) -> ModelCapabilities:
        if isinstance(model, ModelSpec):
            provider = self.registry.get(model.provider)
            if provider is None:
                raise UnknownModelProviderError(f"unknown model provider: {model.provider}")
            return model.capabilities or provider.describe(model)
        return ModelCapabilities()

    @staticmethod
    def fingerprint(model: ModelInput) -> str:
        if isinstance(model, BaseChatModel):
            return f"instance:{id(model)}"
        if isinstance(model, str):
            material = f"string:{model}"
        else:
            material = repr(
                (
                    model.provider,
                    model.model,
                    model.base_url,
                    model.api_key_env,
                    tuple(sorted(model.default_headers.items())),
                    model.temperature,
                    model.max_tokens,
                    model.timeout,
                    model.max_retries,
                    tuple(sorted((key, repr(value)) for key, value in model.params.items())),
                    model.capabilities,
                )
            )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()
