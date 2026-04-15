"""Agentic research loops for stages 2–5.

Two sequential agents:
  1. run_profile_agent — builds the factual company profile (9 CitedFields)
  2. run_news_agent    — finds recent news items within the configured date window

The profile agent passes its seen_urls set to the news agent so pages are
never fetched twice across the two loops.
"""
from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from pathlib import Path
from typing import List

from lib import (
    CRAWL4AI_BROWSER_MODE,
    CRAWL4AI_PAGE_TIMEOUT,
    CRAWL4AI_VERBOSE,
    MAX_NEWS_STEPS,
    MAX_PROFILE_STEPS,
    MAX_CONTENT_CHARS,
    NEWS_WINDOW_DAYS,
    OPENAI_MODEL,
    PROMPTS_DIR,
    ai,
    api_call_with_retry,
    console,
    content_hash,
    save_json,
)
from models import CompanyProfileDraft, FetchedContent, IdentityDraft, NewsDraft
from search import SearchProvider

# ── Tool definitions ──────────────────────────────────────────────────────────

_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search",
        "description": "Search the web to discover URLs and snippets worth reading.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query to run"},
            },
            "required": ["query"],
        },
    },
}

_FETCH_TOOL = {
    "type": "function",
    "function": {
        "name": "fetch",
        "description": "Fetch and read the text content of a web page.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to fetch"},
            },
            "required": ["url"],
        },
    },
}

PROFILE_TOOLS = [
    _SEARCH_TOOL,
    _FETCH_TOOL,
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "Submit your final company profile. Call this when satisfied with completeness.",
            "parameters": {
                "type": "object",
                "properties": {
                    "profile": {
                        "type": "object",
                        "description": "CompanyProfileDraft — each field is a CitedField",
                    },
                },
                "required": ["profile"],
            },
        },
    },
]

NEWS_TOOLS = [
    _SEARCH_TOOL,
    _FETCH_TOOL,
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "Submit your final news findings. Call this when satisfied with coverage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "news": {
                        "type": "object",
                        "description": "NewsDraft — object with an 'items' array",
                    },
                },
                "required": ["news"],
            },
        },
    },
]


# ── Entry points ──────────────────────────────────────────────────────────────

async def run_profile_agent(
    identity: IdentityDraft,
    searcher: SearchProvider,
    outdir: Path,
) -> tuple[CompanyProfileDraft, set[str]]:
    """Research the company's factual profile. Returns (profile, seen_urls)."""
    console.rule("[bold blue]Profile Agent  (stage 2)")

    today = date.today()
    system_prompt = (PROMPTS_DIR / "profile_agent.system.txt").read_text(encoding="utf-8")
    system_prompt = system_prompt.replace("$current_date", today.strftime("%Y-%m-%d"))

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": _profile_initial_message(identity)},
    ]

    seen_urls: set[str] = set()
    src_counter = 0
    total_prompt_tokens = 0
    total_cached_tokens = 0

    for step in range(MAX_PROFILE_STEPS):
        response = api_call_with_retry(lambda: ai.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            tools=PROFILE_TOOLS,
            tool_choice="required",
        ))
        msg = response.choices[0].message
        messages.append(msg)

        total_prompt_tokens, total_cached_tokens = _log_usage(
            response.usage, total_prompt_tokens, total_cached_tokens
        )

        for tool_call in msg.tool_calls:
            name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)

            console.print(f"  [dim]→ {name}[/dim]({_fmt_args(name, args)})  [dim](step {step + 1}/{MAX_PROFILE_STEPS})[/dim]")

            if name == "finish":
                _log_cache_summary(total_prompt_tokens, total_cached_tokens)
                return _parse_profile(args), seen_urls

            if name == "search":
                result = _tool_search(args["query"], searcher)
            elif name == "fetch":
                src_counter += 1
                result = await _tool_fetch(
                    args["url"], f"src_{src_counter:03d}", seen_urls, outdir
                )
            else:
                result = f"Unknown tool: {name}"

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })

    console.print(f"[yellow]Reached MAX_PROFILE_STEPS ({MAX_PROFILE_STEPS}) — forcing finish.[/yellow]")
    _log_cache_summary(total_prompt_tokens, total_cached_tokens)
    return await _force_finish_profile(messages), seen_urls


async def run_news_agent(
    identity: IdentityDraft,
    searcher: SearchProvider,
    outdir: Path,
    seen_urls: set[str],
) -> NewsDraft:
    """Research recent news. Accepts seen_urls from the profile agent to avoid re-fetching."""
    console.rule("[bold blue]News Agent  (stage 3)")

    today = date.today()
    news_cutoff = today - timedelta(days=NEWS_WINDOW_DAYS)

    system_prompt = (PROMPTS_DIR / "news_agent.system.txt").read_text(encoding="utf-8")
    system_prompt = (
        system_prompt
        .replace("$current_date", today.strftime("%Y-%m-%d"))
        .replace("$news_cutoff_date", news_cutoff.strftime("%Y-%m-%d"))
        .replace("$news_window_days", str(NEWS_WINDOW_DAYS))
    )

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": _news_initial_message(identity)},
    ]

    src_counter = sum(1 for u in seen_urls if u)  # continue src numbering after profile agent
    total_prompt_tokens = 0
    total_cached_tokens = 0

    for step in range(MAX_NEWS_STEPS):
        response = api_call_with_retry(lambda: ai.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            tools=NEWS_TOOLS,
            tool_choice="required",
        ))
        msg = response.choices[0].message
        messages.append(msg)

        total_prompt_tokens, total_cached_tokens = _log_usage(
            response.usage, total_prompt_tokens, total_cached_tokens
        )

        for tool_call in msg.tool_calls:
            name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)

            console.print(f"  [dim]→ {name}[/dim]({_fmt_args(name, args)})  [dim](step {step + 1}/{MAX_NEWS_STEPS})[/dim]")

            if name == "finish":
                _log_cache_summary(total_prompt_tokens, total_cached_tokens)
                return _parse_news(args)

            if name == "search":
                result = _tool_search(args["query"], searcher)
            elif name == "fetch":
                src_counter += 1
                result = await _tool_fetch(
                    args["url"], f"src_{src_counter:03d}", seen_urls, outdir
                )
            else:
                result = f"Unknown tool: {name}"

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })

    console.print(f"[yellow]Reached MAX_NEWS_STEPS ({MAX_NEWS_STEPS}) — forcing finish.[/yellow]")
    _log_cache_summary(total_prompt_tokens, total_cached_tokens)
    return await _force_finish_news(messages)


# ── Tool implementations ──────────────────────────────────────────────────────

def _tool_search(query: str, searcher: SearchProvider) -> str:
    try:
        results = searcher.search(query, max_results=5)
    except Exception as e:
        return f"Search failed: {e}"

    if not results:
        return "No results found."

    lines = []
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r.title or '(no title)'}\n   URL: {r.url}\n   {r.snippet or ''}")
    return "\n\n".join(lines)


async def _tool_fetch(
    url: str,
    source_id: str,
    seen_urls: set[str],
    outdir: Path,
) -> str:
    if url in seen_urls:
        return f"Already fetched: {url}"

    seen_urls.add(url)
    fetched_dir = outdir / "fetched"
    fetched_dir.mkdir(exist_ok=True)

    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
        from crawl4ai.async_crawler_strategy import AsyncPlaywrightCrawlerStrategy
        from crawl4ai.async_logger import AsyncLogger

        log_file = str(fetched_dir / f"{source_id}.crawl4ai.log")
        crawler_logger = AsyncLogger(
            log_file=log_file,
            verbose=CRAWL4AI_VERBOSE,
        )

        browser_config = BrowserConfig(
            enable_stealth=(CRAWL4AI_BROWSER_MODE == "stealth"),
            verbose=CRAWL4AI_VERBOSE,
        )

        if CRAWL4AI_BROWSER_MODE == "undetected":
            from crawl4ai import UndetectedAdapter
            strategy = AsyncPlaywrightCrawlerStrategy(
                browser_config=browser_config,
                browser_adapter=UndetectedAdapter(),
                logger=crawler_logger,
            )
        else:
            strategy = AsyncPlaywrightCrawlerStrategy(
                browser_config=browser_config,
                logger=crawler_logger,
            )

        timeout_s = CRAWL4AI_PAGE_TIMEOUT / 1000 * 2  # 2× page_timeout as hard wall-clock cap
        async with AsyncWebCrawler(crawler_strategy=strategy) as crawler:
            result = await asyncio.wait_for(
                crawler.arun(
                    url=url,
                    config=CrawlerRunConfig(
                        page_timeout=CRAWL4AI_PAGE_TIMEOUT,
                        verbose=CRAWL4AI_VERBOSE,
                    ),
                ),
                timeout=timeout_s,
            )

        _dump_raw(result, source_id, fetched_dir)

        if not result.success:
            reason = getattr(result, "error_message", None) or "(no error_message)"
            console.print(f"  [red]✗ fetch failed[/red] {url}\n    reason: {reason}")
            return f"Fetch failed for {url}: {reason}"

        markdown = result.markdown or ""
        metadata = result.metadata or {}

        fc = FetchedContent(
            source_id=source_id,
            url=url,
            canonical_url=result.url or url,
            title=metadata.get("title"),
            published_at=metadata.get("published_date"),
            content_hash=content_hash(markdown),
            markdown=markdown,
        )
        save_json(fetched_dir / f"{source_id}.json", fc)

        if MAX_CONTENT_CHARS is not None and len(markdown) > MAX_CONTENT_CHARS:
            snippet = markdown[:MAX_CONTENT_CHARS] + "\n[...truncated...]"
        else:
            snippet = markdown
        return f"URL: {fc.canonical_url}\nTitle: {fc.title or '(unknown)'}\nPublished: {fc.published_at or 'unknown'}\n\n{snippet}"

    except Exception as e:
        console.print(f"  [red]✗ fetch exception[/red] {url}\n    {type(e).__name__}: {e}")
        return f"Fetch error for {url}: {type(e).__name__}: {e}"


def _dump_raw(result, source_id: str, fetched_dir: Path) -> None:
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


# ── Finish handling ───────────────────────────────────────────────────────────

def _parse_profile(args: dict) -> CompanyProfileDraft:
    try:
        if not args:
            console.print("  [red bold]finish() called with empty args — profile agent produced no output[/red bold]")
            return CompanyProfileDraft()

        data = args.get("profile", args)  # accept both {"profile": {...}} and top-level
        if data is args and "profile" not in args:
            console.print(
                f"  [yellow]finish() missing 'profile' key — attempting top-level parse[/yellow]\n"
                f"  keys present: {list(args.keys())}"
            )
        profile = CompanyProfileDraft(**data)
        populated = sum(1 for f in profile.model_fields if getattr(profile, f).value is not None)
        if populated == 0:
            console.print("  [red bold]Profile has no populated fields — agent produced no output[/red bold]")
        return profile

    except Exception as e:
        console.print(f"  [red]_parse_profile failed: {e}[/red]\n  raw args: {json.dumps(args, indent=2, default=str)[:2000]}")
        raise


def _parse_news(args: dict) -> NewsDraft:
    try:
        if not args:
            console.print("  [red bold]finish() called with empty args — news agent produced no output[/red bold]")
            return NewsDraft()

        data = args.get("news", args)  # accept both {"news": {...}} and top-level
        if data is args and "news" not in args:
            console.print(
                f"  [yellow]finish() missing 'news' key — attempting top-level parse[/yellow]\n"
                f"  keys present: {list(args.keys())}"
            )
        return NewsDraft(**data)

    except Exception as e:
        console.print(f"  [red]_parse_news failed: {e}[/red]\n  raw args: {json.dumps(args, indent=2, default=str)[:2000]}")
        raise


async def _force_finish_profile(messages: list[dict]) -> CompanyProfileDraft:
    messages.append({
        "role": "user",
        "content": "You have reached the research step limit. You must call finish() now with whatever you have gathered so far.",
    })
    response = api_call_with_retry(lambda: ai.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        tools=PROFILE_TOOLS,
        tool_choice={"type": "function", "function": {"name": "finish"}},
    ))
    args = json.loads(response.choices[0].message.tool_calls[0].function.arguments)
    return _parse_profile(args)


async def _force_finish_news(messages: list[dict]) -> NewsDraft:
    messages.append({
        "role": "user",
        "content": "You have reached the research step limit. You must call finish() now with whatever you have gathered so far.",
    })
    response = api_call_with_retry(lambda: ai.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        tools=NEWS_TOOLS,
        tool_choice={"type": "function", "function": {"name": "finish"}},
    ))
    args = json.loads(response.choices[0].message.tool_calls[0].function.arguments)
    return _parse_news(args)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _profile_initial_message(identity: IdentityDraft) -> str:
    return (
        f"Research this company and build a comprehensive factual profile.\n\n"
        f"Company identity:\n{identity.model_dump_json(indent=2)}"
    )


def _news_initial_message(identity: IdentityDraft) -> str:
    return (
        f"Find recent news about this company.\n\n"
        f"Company identity:\n{identity.model_dump_json(indent=2)}"
    )


def _log_usage(
    usage,
    total_prompt_tokens: int,
    total_cached_tokens: int,
) -> tuple[int, int]:
    if not usage:
        return total_prompt_tokens, total_cached_tokens
    prompt_tokens = usage.prompt_tokens or 0
    cached_tokens = (
        usage.prompt_tokens_details.cached_tokens
        if usage.prompt_tokens_details
        else 0
    ) or 0
    total_prompt_tokens += prompt_tokens
    total_cached_tokens += cached_tokens
    cache_pct = int(cached_tokens / prompt_tokens * 100) if prompt_tokens else 0
    console.print(
        f"  [dim]tokens: {prompt_tokens} prompt ({cache_pct}% cached), "
        f"{usage.completion_tokens} completion[/dim]"
    )
    return total_prompt_tokens, total_cached_tokens


def _log_cache_summary(total_prompt: int, total_cached: int) -> None:
    if not total_prompt:
        return
    pct = int(total_cached / total_prompt * 100)
    console.print(
        f"  [dim]cache summary: {total_cached:,}/{total_prompt:,} prompt tokens cached ({pct}%)[/dim]"
    )


def _fmt_args(name: str, args: dict) -> str:
    if name == "search":
        return f'"{args.get("query", "")}"'
    if name == "fetch":
        url = args.get("url", "")
        return f'"{url[:70]}{"…" if len(url) > 70 else ""}"'
    return ""
