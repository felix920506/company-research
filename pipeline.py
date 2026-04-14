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
import sys
from typing import List, Optional

from lib import MAX_LOOP_ITERATIONS, OPENAI_API_KEY, console, save_json
from models import CompanyProfileDraft, NewsDraft
from search import SearchProvider, get_provider
from stages import (
    human_gate_identity,
    human_gate_output,
    stage1_identity,
    stage2_discover,
    stage3_fetch,
    stage4_extract,
    stage5_feedback,
    stage6_output,
)
from rich.panel import Panel


async def run_pipeline(company_input: str, searcher: SearchProvider) -> None:
    console.print(Panel(
        f"[bold]Company Research Pipeline[/bold]\n"
        f"Researching: [cyan]{company_input}[/cyan]\n"
        f"Search provider: [dim]{type(searcher).__name__}[/dim]",
        style="blue",
    ))

    # Stage 1 — identity (human-gated)
    identity, history = stage1_identity(company_input, searcher)
    identity, outdir = human_gate_identity(company_input, identity, history, searcher)

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
    profile = profile or CompanyProfileDraft()
    news = news or NewsDraft()
    report_md = stage6_output(identity, profile, news, outdir)
    human_gate_output(report_md, identity, profile, news, outdir)


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
