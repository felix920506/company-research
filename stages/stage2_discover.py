from __future__ import annotations

from typing import List

from lib import MAX_SOURCES_PER_ITERATION, NEWS_WINDOW_DAYS, ai_call, console, prompt
from models import IdentityDraft, Source
from search import SearchProvider


def stage2_discover(
    identity: IdentityDraft,
    extra_queries: List[str],
    seen_urls: set[str],
    searcher: SearchProvider,
) -> List[Source]:
    console.rule("[bold blue]Stage 2: Source Discovery")

    extra = "\n".join(f"- {q}" for q in extra_queries) if extra_queries else "None"

    with console.status("Generating research sources..."):
        data = ai_call(
            prompt("stage2_discover", "system"),
            prompt("stage2_discover", "user",
                   resolved_name=identity.resolved_name,
                   website=identity.website or "unknown",
                   entity_type=identity.entity_type or "unknown",
                   extra=extra,
                   news_window_days=NEWS_WINDOW_DAYS),
        )

    sources: List[Source] = []
    src_idx = len(seen_urls) + 1

    for url in data.get("seed_urls", []):
        if url not in seen_urls:
            sources.append(Source(source_id=f"src_{src_idx:03d}", url=url, category="official"))
            seen_urls.add(url)
            src_idx += 1

    for query in data.get("search_queries", [])[:5]:
        console.print(f"  Searching: [dim]{query}[/dim]")
        try:
            results = searcher.search(query, max_results=3)
            for r in results:
                if r.url not in seen_urls:
                    sources.append(Source(
                        source_id=f"src_{src_idx:03d}",
                        url=r.url,
                        query_used=query,
                        category="news",
                    ))
                    seen_urls.add(r.url)
                    src_idx += 1
        except Exception as e:
            console.print(f"  [yellow]Search failed for '{query}': {e}[/yellow]")

    console.print(f"  Found [green]{len(sources)}[/green] new sources")
    return sources[:MAX_SOURCES_PER_ITERATION]
