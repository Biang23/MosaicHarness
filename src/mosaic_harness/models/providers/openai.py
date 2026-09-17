from __future__ import annotations

from importlib import import_module
from typing import cast

from langchain_core.language_models import BaseChatModel

from ...core.models import ModelCapabilities, ModelSpec
from ..registry import ModelProvider
from .common import constructor_kwargs


class OpenAIProvider(ModelProvider):
    name = "openai"
    optional_dependency = "langchain-openai"
    install_extra = "openai"

    def build(self, spec: ModelSpec) -> BaseChatModel:
        try:
            module = import_module("langchain_openai")
        except ImportError as exc:
            raise ImportError("langchain_openai is not installed") from exc
        chat_openai = module.__dict__["ChatOpenAI"]
        kwargs = constructor_kwargs(spec, "OPENAI_API_KEY")
        kwargs.setdefault("use_responses_api", False)
        return cast(BaseChatModel, chat_openai(model=spec.model, **kwargs))

    def describe(self, spec: ModelSpec) -> ModelCapabilities:
        del spec
        return ModelCapabilities(streaming=True, tool_calling=None, structured_output=None)
