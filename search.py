"""
Search provider abstraction.

To add a new provider, subclass SearchProvider and implement search().
Select the active provider via the SEARCH_PROVIDER env var or by passing
a provider instance directly to the pipeline.

Built-in providers:
  - duckduckgo  (default, no API key required)
  - brave       (requires BRAVE_API_KEY)
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import List

from models import SearchResult


class SearchProvider(ABC):
    @abstractmethod
    def search(self, query: str, max_results: int = 5) -> List[SearchResult]:
        """Return up to max_results results for query."""


class DuckDuckGoProvider(SearchProvider):
    """Free search via duckduckgo-search. No API key needed."""

    def search(self, query: str, max_results: int = 5) -> List[SearchResult]:
        from ddgs import DDGS

        with DDGS() as ddgs:
            raw = ddgs.text(query, max_results=max_results)
        return [
            SearchResult(url=r["href"], title=r.get("title"), snippet=r.get("body"))
            for r in (raw or [])
            if r.get("href")
        ]


class BraveProvider(SearchProvider):
    """Brave Search API. Requires BRAVE_API_KEY env var."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ["BRAVE_API_KEY"]

    def search(self, query: str, max_results: int = 5) -> List[SearchResult]:
        import urllib.parse

        import urllib.request, json as _json

        url = (
            "https://api.search.brave.com/res/v1/web/search?"
            + urllib.parse.urlencode({"q": query, "count": max_results})
        )
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": self.api_key,
            },
        )
        with urllib.request.urlopen(req) as resp:
            data = _json.loads(resp.read())

        results = data.get("web", {}).get("results", [])
        return [
            SearchResult(
                url=r["url"],
                title=r.get("title"),
                snippet=r.get("description"),
            )
            for r in results
        ]


# ── Factory ───────────────────────────────────────────────────────────────────

_PROVIDERS: dict[str, type[SearchProvider]] = {
    "duckduckgo": DuckDuckGoProvider,
    "brave": BraveProvider,
}


def get_provider(name: str | None = None) -> SearchProvider:
    """Return a provider instance based on SEARCH_PROVIDER env var or name."""
    name = (name or os.environ.get("SEARCH_PROVIDER", "duckduckgo")).lower()
    cls = _PROVIDERS.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown search provider '{name}'. "
            f"Available: {', '.join(_PROVIDERS)}"
        )
    return cls()
