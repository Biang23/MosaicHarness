from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SearchQuery:
    query: str
    max_results: int = 5
    freshness: str | None = None
    domains: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.query.strip():
            raise ValueError("search query must not be empty")
        if not 1 <= self.max_results <= 50:
            raise ValueError("max_results must be between 1 and 50")


@dataclass(frozen=True, slots=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str
    published_at: str | None = None


@dataclass(frozen=True, slots=True)
class SearchResponse:
    query: str
    results: tuple[SearchResult, ...]
    provider: str = "unknown"
