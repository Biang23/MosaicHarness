from __future__ import annotations

import asyncio
from importlib import import_module

from .models import SearchQuery, SearchResponse, SearchResult


class DDGSProvider:
    name = "ddgs"

    async def search(self, query: SearchQuery) -> SearchResponse:
        try:
            ddgs = import_module("ddgs")
        except ImportError as exc:
            raise ImportError("ddgs is required for the ddgs web provider") from exc

        raw_results = await asyncio.to_thread(
            lambda: list(ddgs.DDGS().text(query.query, max_results=query.max_results))
        )
        results = tuple(
            SearchResult(
                title=str(item.get("title", "Untitled")),
                url=str(item.get("href") or item.get("link") or ""),
                snippet=str(item.get("body", "")),
                source=self.name,
            )
            for item in raw_results
        )
        return SearchResponse(query=query.query, results=results, provider=self.name)
