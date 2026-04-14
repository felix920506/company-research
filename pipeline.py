#!/usr/bin/env python3
"""Company research pipeline.

Usage:
    python pipeline.py "Acme Corp"

Environment variables (see .env.example):
    OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL,
    MAX_LOOP_ITERATIONS, SEARCH_PROVIDER
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from string import Template
from typing import List, Optional

from dotenv import load_dotenv
from openai import OpenAI
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from models import (
    CompanyProfileDraft,
    FetchedContent,
    FeedbackResult,
    IdentityDraft,
    NewsDraft,
    Source,
)
from search import SearchProvider, get_provider

load_dotenv()
console = Console()

# ── Config ────────────────────────────────────────────────────────────────────

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
MAX_LOOP_ITERATIONS = int(os.environ.get("MAX_LOOP_ITERATIONS", "3"))
MAX_SOURCES_PER_ITERATION = 10
MAX_CONTENT_CHARS = 3000  # per source before sending to AI
NEWS_WINDOW_DAYS = 90

ai = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

PROMPTS_DIR = Path(__file__).parent / "prompts"


def prompt(name: str, role: str, **kwargs) -> str:
    """Load a prompt template and substitute $variables."""
    template = (PROMPTS_DIR / f"{name}.{role}.txt").read_text(encoding="utf-8")
    return Template(template).substitute(kwargs)


# ── Utilities ─────────────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text[:64]


def output_dir(name: str) -> Path:
    path = Path("output") / slugify(name)
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_json(path: Path, data) -> None:
    if hasattr(data, "model_dump"):
        content = data.model_dump()
    elif isinstance(data, list):
        content = [d.model_dump() if hasattr(d, "model_dump") else d for d in data]
    else:
        content = data
    path.write_text(json.dumps(content, indent=2, default=str))


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def ai_call(system: str, user: str) -> dict:
    """Call the AI with JSON mode and return the parsed response."""
    response = ai.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
        temperature=0.1,
    )
    return json.loads(response.choices[0].message.content)


# ── Stage 1: Identity Resolution ──────────────────────────────────────────────

def stage1_identity(company_input: str) -> IdentityDraft:
    console.rule("[bold blue]Stage 1: Identity Resolution")

    with console.status("Resolving company identity..."):
        data = ai_call(
            prompt("stage1_identity", "system"),
            prompt("stage1_identity", "user", company_input=company_input),
        )

    return IdentityDraft(**data)


def human_gate_identity(company_input: str, identity: IdentityDraft) -> tuple[IdentityDraft, Path]:
    """Show resolved identity, ask for confirmation, return (identity, outdir)."""
    table = Table(title="Resolved Company Identity", show_header=False, box=None)
    table.add_column("Field", style="cyan", min_width=16)
    table.add_column("Value")

    table.add_row("Resolved name", identity.resolved_name or "—")
    table.add_row("Legal name", identity.legal_name or "—")
    table.add_row("Website", identity.website or "—")
    table.add_row("Type", identity.entity_type or "—")
    table.add_row("Jurisdiction", identity.jurisdiction or "—")
    if identity.aliases:
        table.add_row("Aliases", ", ".join(identity.aliases))
    if identity.identifiers:
        table.add_row("Identifiers", ", ".join(f"{k}: {v}" for k, v in identity.identifiers.items()))
    if identity.ambiguities:
        table.add_row("[yellow]Ambiguities[/yellow]", "\n".join(identity.ambiguities))

    console.print(table)

    if not Confirm.ask("Is this the correct company?"):
        clarification = Prompt.ask("Please clarify (e.g. 'Apple Records, not Apple Inc.')")
        return human_gate_identity(clarification, stage1_identity(clarification))

    outdir = output_dir(identity.resolved_name)
    save_json(outdir / "identity.json", identity)
    return identity, outdir


# ── Stage 2: Source Discovery ─────────────────────────────────────────────────

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


# ── Stage 3: Content Fetching ─────────────────────────────────────────────────

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
                # Dump raw crawl4ai result in human-readable form
                sid = source.source_id
                meta = {
                    "url": result.url,
                    "success": result.success,
                    "error_message": getattr(result, "error_message", None),
                    "metadata": result.metadata,
                    "links": result.links,
                    "media": result.media,
                }
                (fetched_dir / f"{sid}.meta.json").write_text(
                    json.dumps(meta, indent=2, default=str)
                )
                if result.markdown:
                    (fetched_dir / f"{sid}.md").write_text(result.markdown)
                if result.cleaned_html:
                    (fetched_dir / f"{sid}.html").write_text(result.cleaned_html)

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


# ── Stage 4: Fact & News Extraction ──────────────────────────────────────────

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


# ── Stage 5: Dynamic Feedback ─────────────────────────────────────────────────

def stage5_feedback(
    profile: CompanyProfileDraft,
    news: NewsDraft,
    iteration: int,
) -> FeedbackResult:
    console.rule(f"[bold blue]Stage 5: Gap Analysis  [iteration {iteration + 1}/{MAX_LOOP_ITERATIONS}]")

    with console.status("Analysing research gaps..."):
        data = ai_call(
            prompt("stage5_feedback", "system"),
            prompt("stage5_feedback", "user",
                   profile_json=profile.model_dump_json(indent=2),
                   news_item_count=len(news.items)),
        )

    result = FeedbackResult(**data)

    if result.has_gaps:
        console.print(f"  [yellow]Gaps detected:[/yellow] {result.notes}")
        if result.missing_fields:
            console.print(f"  Missing: {', '.join(result.missing_fields)}")
    else:
        console.print("  [green]Research looks complete — no critical gaps.[/green]")

    return result


# ── Stage 6: Final Output ─────────────────────────────────────────────────────

def stage6_output(
    identity: IdentityDraft,
    profile: CompanyProfileDraft,
    news: NewsDraft,
    outdir: Path,
) -> str:
    console.rule("[bold blue]Stage 6: Report Generation")

    today = datetime.now().strftime("%Y-%m-%d")

    with console.status("Writing report..."):
        data = ai_call(
            prompt("stage6_output", "system"),
            prompt("stage6_output", "user",
                   resolved_name=identity.resolved_name,
                   today=today,
                   profile_json=profile.model_dump_json(indent=2),
                   news_json=news.model_dump_json(indent=2)),
        )

    report_md: str = data["report"]

    save_json(outdir / "report_draft.json", {
        "identity": identity.model_dump(),
        "profile": profile.model_dump(),
        "news": news.model_dump(),
        "generated_at": datetime.now().isoformat(),
    })

    return report_md


def _save_final(report_md: str, identity: IdentityDraft, profile: CompanyProfileDraft, news: NewsDraft, outdir: Path) -> None:
    (outdir / "final.md").write_text(report_md)
    save_json(outdir / "final.json", {
        "identity": identity.model_dump(),
        "profile": profile.model_dump(),
        "news": news.model_dump(),
        "report_md": report_md,
        "finalized_at": datetime.now().isoformat(),
    })
    console.print(f"\n[green]Saved:[/green] {outdir}/final.md  and  {outdir}/final.json")


def human_gate_output(
    report_md: str,
    identity: IdentityDraft,
    profile: CompanyProfileDraft,
    news: NewsDraft,
    outdir: Path,
) -> None:
    console.rule("[bold green]Final Report Preview")
    console.print(Markdown(report_md))
    console.rule()

    if Confirm.ask("Save this report as final?"):
        _save_final(report_md, identity, profile, news, outdir)
    else:
        refinement = Prompt.ask("What would you like changed?")
        with console.status("Refining report..."):
            data = ai_call(
                prompt("refine_report", "system"),
                prompt("refine_report", "user", report_md=report_md, refinement=refinement),
            )
        human_gate_output(data["report"], identity, profile, news, outdir)


# ── Orchestration ─────────────────────────────────────────────────────────────

async def run_pipeline(company_input: str, searcher: SearchProvider) -> None:
    console.print(Panel(
        f"[bold]Company Research Pipeline[/bold]\n"
        f"Researching: [cyan]{company_input}[/cyan]\n"
        f"Search provider: [dim]{type(searcher).__name__}[/dim]",
        style="blue",
    ))

    # Stage 1 — identity (human-gated)
    identity = stage1_identity(company_input)
    identity, outdir = human_gate_identity(company_input, identity)

    profile: Optional[CompanyProfileDraft] = None
    news: Optional[NewsDraft] = None
    seen_urls: set[str] = set()
    extra_queries: List[str] = []

    # Stages 2-5 — autonomous research loop
    for iteration in range(MAX_LOOP_ITERATIONS):
        console.print(f"\n[bold]Research loop — pass {iteration + 1} of {MAX_LOOP_ITERATIONS}[/bold]")

        sources = stage2_discover(identity, extra_queries, seen_urls, searcher)
        save_json(outdir / "sources.json", sources)

        if not sources:
            console.print("[yellow]No new sources found — stopping loop early.[/yellow]")
            break

        fetched = await stage3_fetch(sources, outdir)
        profile, news = stage4_extract(identity, fetched, profile, news)

        save_json(outdir / "profile_draft.json", profile)
        save_json(outdir / "news_draft.json", news)

        feedback = stage5_feedback(profile, news, iteration)

        if not feedback.has_gaps:
            break

        if iteration < MAX_LOOP_ITERATIONS - 1:
            extra_queries = feedback.follow_up_queries
        else:
            console.print(f"[yellow]Reached max iterations ({MAX_LOOP_ITERATIONS}) — proceeding to output.[/yellow]")

    # Stage 6 — final output (human-gated)
    report_md = stage6_output(
        identity,
        profile or CompanyProfileDraft(),
        news or NewsDraft(),
        outdir,
    )
    human_gate_output(report_md, identity, profile or CompanyProfileDraft(), news or NewsDraft(), outdir)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Research a company and generate a cited report.")
    parser.add_argument("company", help="Company name or description")
    parser.add_argument(
        "--search-provider",
        default=None,
        help="Search provider to use (overrides SEARCH_PROVIDER env var). "
             "Available: duckduckgo, brave",
    )
    args = parser.parse_args()

    if not OPENAI_API_KEY:
        console.print("[red]Error: OPENAI_API_KEY is not set. Add it to .env or the environment.[/red]")
        sys.exit(1)

    searcher = get_provider(args.search_provider)
    asyncio.run(run_pipeline(args.company, searcher))


if __name__ == "__main__":
    main()
