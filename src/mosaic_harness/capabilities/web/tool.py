from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field, PrivateAttr

from ..builtins.base import MosaicTool
from ..tools.result import ToolResult
from .models import SearchQuery
from .provider import SearchProvider


class WebSearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=2_000)
    max_results: int = Field(default=5, ge=1, le=50)
    freshness: str | None = None
    domains: list[str] = Field(default_factory=list)


class WebSearchTool(MosaicTool):
    name: str = "web_search"
    description: str = "Search public web sources and return citation-ready results."
    category = "network"
    risk_level = "medium"
    required_categories = ("network",)
    _provider: SearchProvider = PrivateAttr()

    def __init__(self, *, provider: SearchProvider, **kwargs: Any) -> None:
        kwargs.setdefault("args_schema", WebSearchArgs)
        super().__init__(**kwargs)
        self._provider = provider

    def _run(
        self,
        query: str,
        max_results: int = 5,
        freshness: str | None = None,
        domains: Sequence[str] = (),
        **kwargs: object,
    ) -> ToolResult:
        del kwargs
        return asyncio.run(self._search(query, max_results, freshness, domains))

    async def _arun(
        self,
        query: str,
        max_results: int = 5,
        freshness: str | None = None,
        domains: Sequence[str] = (),
        **kwargs: object,
    ) -> ToolResult:
        del kwargs
        return await self._search(query, max_results, freshness, domains)

    async def _search(
        self,
        query: str,
        max_results: int,
        freshness: str | None,
        domains: Sequence[str],
    ) -> ToolResult:
        response = await self._provider.search(
            SearchQuery(
                query=query,
                max_results=max_results,
                freshness=freshness,
                domains=tuple(domains),
            )
        )
        results = [
            {
                "title": item.title,
                "url": item.url,
                "snippet": item.snippet,
                "source": item.source,
                "published_at": item.published_at,
            }
            for item in response.results
        ]
        return ToolResult.success(
            f"Found {len(results)} web results",
            data={"query": response.query, "provider": response.provider, "results": results},
            artifacts=tuple(str(item["url"]) for item in results),
        )
