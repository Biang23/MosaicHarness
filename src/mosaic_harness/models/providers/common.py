from __future__ import annotations

import os
from typing import Any

from ...core.models import ModelSpec


def constructor_kwargs(spec: ModelSpec, default_api_key_env: str) -> dict[str, Any]:
    kwargs = dict(spec.params)
    api_key = spec.api_key or os.getenv(spec.api_key_env or default_api_key_env)
    if api_key is not None:
        kwargs["api_key"] = api_key
    if spec.base_url is not None:
        kwargs["base_url"] = spec.base_url
    if spec.default_headers:
        kwargs["default_headers"] = dict(spec.default_headers)
    if spec.temperature is not None:
        kwargs["temperature"] = spec.temperature
    if spec.max_tokens is not None:
        kwargs["max_tokens"] = spec.max_tokens
    if spec.timeout is not None:
        kwargs["timeout"] = spec.timeout
    if spec.max_retries is not None:
        kwargs["max_retries"] = spec.max_retries
    return kwargs
