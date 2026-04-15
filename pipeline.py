#!/usr/bin/env python3
"""Company research pipeline.

Usage:
    python pipeline.py "Acme Corp"

Environment variables (see .env.example):
    OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL,
    MAX_PROFILE_STEPS, MAX_NEWS_STEPS, MAX_AGENT_STEPS, SEARCH_PROVIDER
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from rich.panel import Panel

from lib import OPENAI_API_KEY, console, save_json
from search import SearchProvider, get_provider
from stages import (
    human_gate_identity,
    human_gate_output,
    run_news_agent,
    run_profile_agent,
    stage1_identity,
    stage6_output,
)


async def run_pipeline(company_input: str, searcher: SearchProvider) -> None:
    console.print(Panel(
        f"[bold]Company Research Pipeline[/bold]\n"
        f"Researching: [cyan]{company_input}[/cyan]\n"
        f"Search provider: [dim]{type(searcher).__name__}[/dim]",
        style="blue",
    ))

    # Stage 1 — identity resolution (human-gated)
    identity, history = await stage1_identity(company_input, searcher)
    identity, outdir = await human_gate_identity(company_input, identity, history, searcher)

    # Stage 2 — profile research
    profile, seen_urls = await run_profile_agent(identity, searcher, outdir)
    save_json(outdir / "profile_draft.json", profile)

    # Stage 3 — news research (reuses seen_urls to avoid re-fetching)
    news = await run_news_agent(identity, searcher, outdir, seen_urls)
    save_json(outdir / "news_draft.json", news)

    # Stage 6 — report generation (human-gated)
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
