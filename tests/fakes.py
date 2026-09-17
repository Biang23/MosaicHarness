from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field, PrivateAttr


class ScriptedChatModel(BaseChatModel):
    responses: list[AIMessage] = Field(default_factory=list)
    seen_messages: list[list[BaseMessage]] = Field(default_factory=list)
    _bound_tools: Sequence[Any] = PrivateAttr(default=())

    @property
    def _llm_type(self) -> str:
        return "mosaic-scripted"

    def bind_tools(
        self,
        tools: Sequence[Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> ScriptedChatModel:
        del tool_choice, kwargs
        self._bound_tools = tools
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        self.seen_messages.append(list(messages))
        if not self.responses:
            raise AssertionError("No scripted model response remains")
        return ChatResult(generations=[ChatGeneration(message=self.responses.pop(0))])


class CountingChatModel(BaseChatModel):
    seen_messages: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "mosaic-counting"

    def bind_tools(
        self,
        tools: Sequence[Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> CountingChatModel:
        del tools, tool_choice, kwargs
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        self.seen_messages.append(list(messages))
        human_count = sum(message.type == "human" for message in messages)
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=f"human_messages={human_count}"))]
        )
