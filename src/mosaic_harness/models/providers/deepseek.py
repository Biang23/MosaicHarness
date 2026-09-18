from __future__ import annotations

from importlib import import_module
from typing import cast

from langchain_core.language_models import BaseChatModel

from ...core.models import ModelCapabilities, ModelSpec
from ..registry import ModelProvider
from .common import constructor_kwargs


class DeepSeekProvider(ModelProvider):
    name = "deepseek"
    optional_dependency = "langchain-deepseek"
    install_extra = "deepseek"
    module_name = "langchain_deepseek"
    credential_env = "DEEPSEEK_API_KEY"

    def build(self, spec: ModelSpec) -> BaseChatModel:
        try:
            module = import_module("langchain_deepseek")
        except ImportError as exc:
            raise ImportError("langchain_deepseek is not installed") from exc
        chat_deepseek = module.__dict__["ChatDeepSeek"]
        kwargs = constructor_kwargs(spec, "DEEPSEEK_API_KEY")
        return cast(BaseChatModel, chat_deepseek(model=spec.model, **kwargs))

    def describe(self, spec: ModelSpec) -> ModelCapabilities:
        if spec.model.lower() in {"deepseek-reasoner", "deepseek-r1"}:
            return ModelCapabilities(
                tool_calling=False,
                streaming=True,
                structured_output=False,
                reasoning=True,
            )
        return ModelCapabilities(
            tool_calling=True,
            streaming=True,
            structured_output=True,
            reasoning=False,
        )
