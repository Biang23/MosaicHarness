from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from langchain_core.language_models import BaseChatModel

from ..core.models import ModelCapabilities, ModelSpec


class ModelProvider(Protocol):
    name: str
    optional_dependency: str
    install_extra: str

    def build(self, spec: ModelSpec) -> BaseChatModel: ...

    def describe(self, spec: ModelSpec) -> ModelCapabilities: ...


ProviderBuilder = Callable[[ModelSpec], BaseChatModel]


class ProviderRegistry:
    def __init__(self, providers: list[ModelProvider] | None = None) -> None:
        self._providers: dict[str, ModelProvider] = {}
        for provider in providers or []:
            self.register(provider)

    def register(self, provider: ModelProvider) -> None:
        self._providers[provider.name] = provider
        for alias in getattr(provider, "aliases", ()):
            self._providers[alias] = provider

    def get(self, name: str) -> ModelProvider | None:
        return self._providers.get(name)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._providers)
