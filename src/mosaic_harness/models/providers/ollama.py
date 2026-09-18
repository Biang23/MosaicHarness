from __future__ import annotations

from importlib import import_module
from typing import cast

from langchain_core.language_models import BaseChatModel

from ...core.models import ModelCapabilities, ModelSpec
from ..registry import ModelProvider


class OllamaProvider(ModelProvider):
    name = "ollama"
    optional_dependency = "langchain-ollama"
    install_extra = "ollama"
    module_name = "langchain_ollama"
    credential_env = None

    def build(self, spec: ModelSpec) -> BaseChatModel:
        try:
            module = import_module("langchain_ollama")
        except ImportError as exc:
            raise ImportError("langchain_ollama is not installed") from exc
        chat_ollama = module.__dict__["ChatOllama"]
        kwargs = dict(spec.params)
        if spec.base_url is not None:
            kwargs["base_url"] = spec.base_url
        if spec.temperature is not None:
            kwargs["temperature"] = spec.temperature
        if spec.max_tokens is not None:
            kwargs["num_predict"] = spec.max_tokens
        if spec.timeout is not None:
            client_kwargs = dict(kwargs.get("client_kwargs", {}))
            client_kwargs["timeout"] = spec.timeout
            kwargs["client_kwargs"] = client_kwargs
        return cast(BaseChatModel, chat_ollama(model=spec.model, **kwargs))

    def describe(self, spec: ModelSpec) -> ModelCapabilities:
        del spec
        return ModelCapabilities(streaming=True, tool_calling=None, structured_output=None)
