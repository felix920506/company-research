from __future__ import annotations

from typing import List, Optional

from lib import MAX_CONTENT_CHARS, NEWS_WINDOW_DAYS, ai_call, console, prompt
from models import CompanyProfileDraft, FetchedContent, IdentityDraft, NewsDraft


def stage4_extract(
    identity: IdentityDraft,
    fetched: List[FetchedContent],
    existing_profile: Optional[CompanyProfileDraft],
    existing_news: Optional[NewsDraft],
) -> tuple[CompanyProfileDraft, NewsDraft]:
    console.rule("[bold blue]Stage 4: Fact & News Extraction")

    if not fetched:
        console.print("[yellow]No content to extract from.[/yellow]")
        return existing_profile or CompanyProfileDraft(), existing_news or NewsDraft()

    existing_profile_json = existing_profile.model_dump_json(indent=2) if existing_profile else "null"
    existing_news_json = existing_news.model_dump_json(indent=2) if existing_news else "null"

    with console.status("Extracting facts and news..."):
        data = ai_call(
            prompt("stage4_extract", "system"),
            prompt("stage4_extract", "user",
                   resolved_name=identity.resolved_name,
                   sources_block=_sources_block(fetched),
                   existing_profile_json=existing_profile_json,
                   existing_news_json=existing_news_json,
                   news_window_days=NEWS_WINDOW_DAYS),
        )

    profile = CompanyProfileDraft(**data["profile"])
    news = NewsDraft(**data["news"])

    fields = CompanyProfileDraft.model_fields
    console.print(
        f"  Profile fields populated: "
        f"[green]{sum(1 for f in fields if getattr(profile, f).value is not None)}[/green]"
        f"/{len(fields)}"
    )
    console.print(f"  News items: [green]{len(news.items)}[/green]")
    return profile, news


def _sources_block(fetched: List[FetchedContent]) -> str:
    parts = []
    for f in fetched:
        snippet = f.markdown[:MAX_CONTENT_CHARS]
        if len(f.markdown) > MAX_CONTENT_CHARS:
            snippet += "\n[...truncated...]"
        parts.append(
            f"--- SOURCE {f.source_id} ---\n"
            f"URL: {f.canonical_url}\n"
            f"Title: {f.title or 'Unknown'}\n"
            f"Published: {f.published_at or 'Unknown'}\n\n"
            f"{snippet}\n"
        )
    return "\n".join(parts)
