from __future__ import annotations

from typing import Protocol

from .models import SearchQuery, SearchResponse


class SearchProvider(Protocol):
    name: str

    async def search(self, query: SearchQuery) -> SearchResponse: ...
