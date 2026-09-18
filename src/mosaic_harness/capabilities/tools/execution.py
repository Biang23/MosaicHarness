from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from langchain.agents.middleware import AgentMiddleware, ToolCallRequest
from langchain_core.messages import ToolMessage

from .result import ToolResult

logger = logging.getLogger(__name__)

ExecutionStatus = Literal["success", "error", "blocked", "timeout"]


@dataclass(frozen=True, slots=True)
class ToolExecutionPolicy:
    """Execution guardrails applied after a model selects a tool."""

    timeout_seconds: float | None = 30.0
    max_retries: int = 0
    retry_on: tuple[type[BaseException], ...] = (TimeoutError, ConnectionError)
    require_approval: bool = False
    permission: str = "default"

    def __post_init__(self) -> None:
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")


@dataclass(frozen=True, slots=True)
class ToolExecutionRecord:
    call_id: str
    tool_name: str
    status: ExecutionStatus
    attempt: int
    duration_ms: float
    error_type: str | None = None
    retryable: bool = False


class ToolExecutionRecorder:
    def __init__(self) -> None:
        self._records: list[ToolExecutionRecord] = []
        self._lock = threading.Lock()

    @property
    def records(self) -> tuple[ToolExecutionRecord, ...]:
        with self._lock:
            return tuple(self._records)

    def record(self, item: ToolExecutionRecord) -> None:
        with self._lock:
            self._records.append(item)


class ToolExecutionMiddleware(AgentMiddleware):
    """Apply approval, timeout, retry, and structured error policies to tools."""

    def __init__(
        self,
        *,
        policies: Mapping[str, ToolExecutionPolicy] | None = None,
        recorder: ToolExecutionRecorder | None = None,
    ) -> None:
        self._policies = dict(policies or {})
        self.recorder = recorder or ToolExecutionRecorder()
        logger.debug("tool.middleware_initialized policies=%d", len(self._policies))

    def wrap_tool_call(self, request: ToolCallRequest, handler: Callable[..., Any]) -> Any:
        return self._run_sync(request, handler)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[..., Awaitable[Any]],
    ) -> Any:
        return await self._run_async(request, handler)

    def _run_sync(self, request: ToolCallRequest, handler: Callable[..., Any]) -> Any:
        name, call_id, policy = self._request_info(request)
        if policy.require_approval:
            return self._blocked(request, name, call_id, policy)
        for attempt in range(1, policy.max_retries + 2):
            started = time.perf_counter()
            try:
                response = _call_sync_with_timeout(handler, request, policy.timeout_seconds)
            except Exception as exc:
                retryable = isinstance(exc, policy.retry_on)
                status: ExecutionStatus = "timeout" if isinstance(exc, TimeoutError) else "error"
                self.recorder.record(
                    ToolExecutionRecord(
                        call_id=call_id,
                        tool_name=name,
                        status=status,
                        attempt=attempt,
                        duration_ms=_duration_ms(started),
                        error_type=type(exc).__name__,
                        retryable=retryable,
                    )
                )
                if retryable and attempt <= policy.max_retries:
                    logger.warning(
                        "tool.retry tool=%s call_id=%s attempt=%d next_attempt=%d error_type=%s",
                        name,
                        call_id,
                        attempt,
                        attempt + 1,
                        type(exc).__name__,
                    )
                    continue
                logger.error(
                    "tool.failed tool=%s call_id=%s attempt=%d error_type=%s retryable=%s",
                    name,
                    call_id,
                    attempt,
                    type(exc).__name__,
                    retryable,
                )
                return _error_message(
                    call_id,
                    f"Tool '{name}' failed: {type(exc).__name__}: {exc}",
                    retryable=retryable,
                )
            self.recorder.record(
                ToolExecutionRecord(
                    call_id=call_id,
                    tool_name=name,
                    status="success",
                    attempt=attempt,
                    duration_ms=_duration_ms(started),
                )
            )
            logger.debug(
                "tool.completed tool=%s call_id=%s attempt=%d duration_ms=%.3f",
                name,
                call_id,
                attempt,
                _duration_ms(started),
            )
            return response
        raise AssertionError("tool execution loop exited without a response")

    async def _run_async(
        self,
        request: ToolCallRequest,
        handler: Callable[..., Awaitable[Any]],
    ) -> Any:
        name, call_id, policy = self._request_info(request)
        if policy.require_approval:
            return self._blocked(request, name, call_id, policy)
        for attempt in range(1, policy.max_retries + 2):
            started = time.perf_counter()
            try:
                response = handler(request)
                if policy.timeout_seconds is not None:
                    response = await asyncio.wait_for(response, policy.timeout_seconds)
                else:
                    response = await response
            except Exception as exc:
                retryable = isinstance(exc, policy.retry_on)
                status: ExecutionStatus = "timeout" if isinstance(exc, TimeoutError) else "error"
                self.recorder.record(
                    ToolExecutionRecord(
                        call_id=call_id,
                        tool_name=name,
                        status=status,
                        attempt=attempt,
                        duration_ms=_duration_ms(started),
                        error_type=type(exc).__name__,
                        retryable=retryable,
                    )
                )
                if retryable and attempt <= policy.max_retries:
                    logger.warning(
                        "tool.retry tool=%s call_id=%s attempt=%d next_attempt=%d error_type=%s",
                        name,
                        call_id,
                        attempt,
                        attempt + 1,
                        type(exc).__name__,
                    )
                    continue
                logger.error(
                    "tool.failed tool=%s call_id=%s attempt=%d error_type=%s retryable=%s",
                    name,
                    call_id,
                    attempt,
                    type(exc).__name__,
                    retryable,
                )
                return _error_message(
                    call_id,
                    f"Tool '{name}' failed: {type(exc).__name__}: {exc}",
                    retryable=retryable,
                )
            self.recorder.record(
                ToolExecutionRecord(
                    call_id=call_id,
                    tool_name=name,
                    status="success",
                    attempt=attempt,
                    duration_ms=_duration_ms(started),
                )
            )
            logger.debug(
                "tool.completed tool=%s call_id=%s attempt=%d duration_ms=%.3f",
                name,
                call_id,
                attempt,
                _duration_ms(started),
            )
            return response
        raise AssertionError("tool execution loop exited without a response")

    def _request_info(self, request: ToolCallRequest) -> tuple[str, str, ToolExecutionPolicy]:
        name = str(request.tool_call.get("name", "unknown_tool"))
        call_id = str(request.tool_call.get("id", ""))
        return name, call_id, self._policies.get(name, ToolExecutionPolicy())

    def _blocked(
        self,
        request: ToolCallRequest,
        name: str,
        call_id: str,
        policy: ToolExecutionPolicy,
    ) -> ToolMessage:
        logger.warning(
            "tool.blocked tool=%s call_id=%s permission=%s",
            name,
            call_id,
            policy.permission,
        )
        self.recorder.record(
            ToolExecutionRecord(
                call_id=call_id,
                tool_name=name,
                status="blocked",
                attempt=1,
                duration_ms=0,
                error_type="ApprovalRequired",
            )
        )
        return _error_message(
            call_id,
            f"Tool '{name}' requires approval before execution.",
            retryable=False,
            next_actions=(f"request_approval:{policy.permission}", "stop_until_approved"),
        )


def _call_sync_with_timeout(
    handler: Callable[..., Any],
    request: ToolCallRequest,
    timeout_seconds: float | None,
) -> Any:
    if timeout_seconds is None:
        return handler(request)
    result: list[Any] = []
    error: list[BaseException] = []

    def invoke() -> None:
        try:
            result.append(handler(request))
        except BaseException as exc:
            error.append(exc)

    worker = threading.Thread(target=invoke, daemon=True)
    worker.start()
    worker.join(timeout_seconds)
    if worker.is_alive():
        raise TimeoutError(f"tool execution exceeded {timeout_seconds:g} seconds")
    if error:
        raise error[0]
    return result[0]


def _error_message(
    call_id: str,
    summary: str,
    *,
    retryable: bool,
    next_actions: tuple[str, ...] = (),
) -> ToolMessage:
    payload = ToolResult.error(
        summary,
        next_actions=next_actions
        or (("retry_with_backoff",) if retryable else ("stop_and_report",)),
    )
    return ToolMessage(content=payload.model_dump_json(), tool_call_id=call_id)


def _duration_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)
