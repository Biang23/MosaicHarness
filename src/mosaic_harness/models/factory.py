from __future__ import annotations

import hashlib
import importlib.util
import logging
import os

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from ..core.errors import MissingOptionalDependencyError, UnknownModelProviderError
from ..core.models import ModelCapabilities, ModelInput, ModelSpec
from .capabilities import ModelInspection, inspect_credential
from .providers import (
    AnthropicProvider,
    DeepSeekProvider,
    MoonshotProvider,
    OllamaProvider,
    OpenAIProvider,
    QwenProvider,
)
from .registry import ModelProvider, ProviderRegistry

logger = logging.getLogger(__name__)


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
            logger.debug("model.reused type=%s", type(model).__name__)
            return model
        if isinstance(model, str):
            try:
                resolved = init_chat_model(model)
                logger.info("model.resolved provider_string=%s", model)
                return resolved
            except ImportError as exc:
                logger.error("model.dependency_missing provider_string=%s", model)
                raise MissingOptionalDependencyError(
                    "model string requires its LangChain provider package; "
                    "install the corresponding Mosaic model extra"
                ) from exc
        provider = self.registry.get(model.provider)
        if provider is None:
            raise UnknownModelProviderError(f"unknown model provider: {model.provider}")
        try:
            resolved = provider.build(model)
            logger.info("model.resolved provider=%s model=%s", model.provider, model.model)
            return resolved
        except ImportError as exc:
            logger.error(
                "model.dependency_missing provider=%s package=%s",
                model.provider,
                provider.optional_dependency,
            )
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
        if isinstance(model, str) and ":" in model:
            provider_name, model_name = model.split(":", 1)
            provider = self.registry.get(provider_name)
            if provider is not None:
                return provider.describe(ModelSpec(provider=provider_name, model=model_name))
        return ModelCapabilities()

    def inspect(self, model: ModelInput) -> ModelInspection:
        if isinstance(model, BaseChatModel):
            response_metadata = getattr(model, "response_metadata", {})
            provider = (
                response_metadata.get("model_provider")
                if isinstance(response_metadata, dict)
                else None
            )
            model_name = getattr(model, "model_name", None) or getattr(model, "model", None)
            return ModelInspection(
                provider=str(provider) if provider else None,
                model=str(model_name) if model_name else None,
                capabilities=ModelCapabilities(),
                provider_installed=True,
                credential_env=None,
                credential_configured=True,
            )
        if isinstance(model, str):
            provider_name, separator, model_name = model.partition(":")
            provider = self.registry.get(provider_name) if separator else None
            if provider is None:
                return ModelInspection(
                    provider=provider_name if separator else None,
                    model=model_name if separator else model,
                    capabilities=ModelCapabilities(),
                    provider_installed=True,
                    credential_env=None,
                    credential_configured=True,
                )
            env_name = getattr(provider, "credential_env", None)
            module_name = getattr(provider, "module_name", None)
            return ModelInspection(
                provider=provider_name,
                model=model_name,
                capabilities=self.describe(model),
                provider_installed=not module_name
                or importlib.util.find_spec(module_name) is not None,
                credential_env=env_name,
                credential_configured=bool(env_name and os.getenv(env_name)),
            )
        provider = self.registry.get(model.provider)
        if provider is None:
            raise UnknownModelProviderError(f"unknown model provider: {model.provider}")
        module_name = getattr(provider, "module_name", None)
        env_name = getattr(provider, "credential_env", None)
        credential_env, configured = inspect_credential(model, env_name)
        return ModelInspection(
            provider=model.provider,
            model=model.model,
            capabilities=self.describe(model),
            provider_installed=not module_name or importlib.util.find_spec(module_name) is not None,
            credential_env=credential_env,
            credential_configured=configured,
        )

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
