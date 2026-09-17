from __future__ import annotations

from importlib import import_module
from typing import cast

from langchain_core.language_models import BaseChatModel

from ...core.models import ModelCapabilities, ModelSpec
from ..registry import ModelProvider
from .common import constructor_kwargs


class MoonshotProvider(ModelProvider):
    name = "kimi"
    aliases = ("moonshot",)
    optional_dependency = "langchain-moonshot"
    install_extra = "kimi"

    def build(self, spec: ModelSpec) -> BaseChatModel:
        try:
            module = import_module("langchain_moonshot")
        except ImportError as exc:
            raise ImportError("langchain_moonshot is not installed") from exc
        chat_moonshot = module.__dict__["ChatMoonshot"]
        kwargs = constructor_kwargs(spec, "MOONSHOT_API_KEY")
        return cast(BaseChatModel, chat_moonshot(model=spec.model, **kwargs))

    def describe(self, spec: ModelSpec) -> ModelCapabilities:
        del spec
        return ModelCapabilities(
            tool_calling=True,
            streaming=True,
            structured_output=True,
            reasoning=True,
        )
