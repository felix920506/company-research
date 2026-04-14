from __future__ import annotations

import json
from pathlib import Path
from typing import List

from lib import console, content_hash, save_json
from models import FetchedContent, Source


async def stage3_fetch(sources: List[Source], outdir: Path) -> List[FetchedContent]:
    console.rule("[bold blue]Stage 3: Content Fetching")
    fetched_dir = outdir / "fetched"
    fetched_dir.mkdir(exist_ok=True)

    fetched: List[FetchedContent] = []

    from crawl4ai import AsyncWebCrawler

    async with AsyncWebCrawler(verbose=False) as crawler:
        for source in sources:
            console.print(f"  Fetching [dim]{source.url[:80]}[/dim]")
            try:
                result = await crawler.arun(url=source.url)
                _dump_raw(result, source.source_id, fetched_dir)

                if result.success:
                    markdown = result.markdown or ""
                    metadata = result.metadata or {}
                    fc = FetchedContent(
                        source_id=source.source_id,
                        url=source.url,
                        canonical_url=result.url or source.url,
                        title=metadata.get("title"),
                        published_at=metadata.get("published_date"),
                        content_hash=content_hash(markdown),
                        markdown=markdown,
                    )
                    save_json(fetched_dir / f"{source.source_id}.json", fc)
                    fetched.append(fc)
                    console.print(f"    [green]✓[/green] {fc.title or source.url[:60]}")
                else:
                    console.print(f"    [yellow]✗[/yellow] fetch failed")
            except Exception as e:
                console.print(f"    [red]✗[/red] {e}")

    console.print(f"  Fetched [green]{len(fetched)}[/green] of {len(sources)} sources")
    return fetched


def _dump_raw(result, source_id: str, fetched_dir: Path) -> None:
    """Write the raw crawl4ai result as human-readable files alongside the structured output."""
    meta = {
        "url": result.url,
        "success": result.success,
        "error_message": getattr(result, "error_message", None),
        "metadata": result.metadata,
        "links": result.links,
        "media": result.media,
    }
    (fetched_dir / f"{source_id}.meta.json").write_text(
        json.dumps(meta, indent=2, default=str)
    )
    if result.markdown:
        (fetched_dir / f"{source_id}.md").write_text(result.markdown)
    if result.cleaned_html:
        (fetched_dir / f"{source_id}.html").write_text(result.cleaned_html)
