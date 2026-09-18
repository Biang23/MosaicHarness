from __future__ import annotations

from importlib import import_module
from typing import cast

from langchain_core.language_models import BaseChatModel

from ...core.models import ModelCapabilities, ModelSpec
from ..registry import ModelProvider
from .common import constructor_kwargs


class QwenProvider(ModelProvider):
    name = "qwen"
    aliases = ("qwq",)
    optional_dependency = "langchain-qwq"
    install_extra = "qwen"
    module_name = "langchain_qwq"
    credential_env = "DASHSCOPE_API_KEY"

    def build(self, spec: ModelSpec) -> BaseChatModel:
        try:
            module = import_module("langchain_qwq")
        except ImportError as exc:
            raise ImportError("langchain_qwq is not installed") from exc
        chat_qwen = module.__dict__["ChatQwen"]
        kwargs = constructor_kwargs(spec, "DASHSCOPE_API_KEY")
        return cast(BaseChatModel, chat_qwen(model=spec.model, **kwargs))

    def describe(self, spec: ModelSpec) -> ModelCapabilities:
        del spec
        return ModelCapabilities(
            tool_calling=True,
            streaming=True,
            structured_output=True,
        )
