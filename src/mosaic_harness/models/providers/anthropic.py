from __future__ import annotations

from importlib import import_module
from typing import cast

from langchain_core.language_models import BaseChatModel

from ...core.models import ModelCapabilities, ModelSpec
from ..registry import ModelProvider
from .common import constructor_kwargs


class AnthropicProvider(ModelProvider):
    name = "anthropic"
    optional_dependency = "langchain-anthropic"
    install_extra = "anthropic"

    def build(self, spec: ModelSpec) -> BaseChatModel:
        try:
            module = import_module("langchain_anthropic")
        except ImportError as exc:
            raise ImportError("langchain_anthropic is not installed") from exc
        chat_anthropic = module.__dict__["ChatAnthropic"]
        kwargs = constructor_kwargs(spec, "ANTHROPIC_API_KEY")
        if "max_tokens" in kwargs:
            kwargs["max_tokens_to_sample"] = kwargs.pop("max_tokens")
        return cast(BaseChatModel, chat_anthropic(model_name=spec.model, **kwargs))

    def describe(self, spec: ModelSpec) -> ModelCapabilities:
        del spec
        return ModelCapabilities(
            tool_calling=True,
            streaming=True,
            structured_output=True,
            parallel_tool_calls=True,
            reasoning=True,
        )
