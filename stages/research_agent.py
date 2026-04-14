"""Agentic research loop for stages 2–5.

A single AI agent receives the company identity and autonomously decides
what to search, what to fetch, and when it has enough to submit findings.
It communicates via tool calls throughout; the loop ends when the agent
calls finish() or the MAX_AGENT_STEPS hard cap is reached.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

from lib import (
    MAX_AGENT_STEPS,
    MAX_CONTENT_CHARS,
    NEWS_WINDOW_DAYS,
    OPENAI_MODEL,
    PROMPTS_DIR,
    ai,
    console,
    content_hash,
    save_json,
)
from models import CompanyProfileDraft, FetchedContent, IdentityDraft, NewsDraft
from search import SearchProvider

# ── Tool definitions ──────────────────────────────────────────────────────────

TOOLS = [
    {
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
    },
    {
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
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": (
                "Submit your final research findings. "
                "Call this when you are satisfied with completeness."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "profile": {
                        "type": "object",
                        "description": "CompanyProfileDraft — each field is a CitedField",
                    },
                    "news": {
                        "type": "object",
                        "description": "NewsDraft — object with an 'items' array",
                    },
                },
                "required": ["profile", "news"],
            },
        },
    },
]


# ── Entry point ───────────────────────────────────────────────────────────────

async def run_research_agent(
    identity: IdentityDraft,
    searcher: SearchProvider,
    outdir: Path,
) -> tuple[CompanyProfileDraft, NewsDraft]:
    """Run the agentic research loop and return structured findings."""
    console.rule("[bold blue]Research Agent  (stages 2–5)")

    system_prompt = (PROMPTS_DIR / "research_agent.system.txt").read_text(encoding="utf-8")
    system_prompt = system_prompt.replace("$news_window_days", str(NEWS_WINDOW_DAYS))

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": _initial_message(identity)},
    ]

    seen_urls: set[str] = set()
    src_counter = 0

    for step in range(MAX_AGENT_STEPS):
        response = ai.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="required",
        )
        msg = response.choices[0].message
        messages.append(msg)

        for tool_call in msg.tool_calls:
            name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)

            console.print(f"  [dim]→ {name}[/dim]({_fmt_args(name, args)})")

            if name == "finish":
                return _parse_finish(args)

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

    console.print(f"[yellow]Reached MAX_AGENT_STEPS ({MAX_AGENT_STEPS}) — forcing finish.[/yellow]")
    return await _force_finish(messages)


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
        from crawl4ai import AsyncWebCrawler

        async with AsyncWebCrawler(verbose=False) as crawler:
            result = await crawler.arun(url=url)

        _dump_raw(result, source_id, fetched_dir)

        if not result.success:
            return f"Fetch failed for {url}"

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

        snippet = markdown[:MAX_CONTENT_CHARS]
        if len(markdown) > MAX_CONTENT_CHARS:
            snippet += "\n[...truncated...]"
        return f"URL: {fc.canonical_url}\nTitle: {fc.title or '(unknown)'}\nPublished: {fc.published_at or 'unknown'}\n\n{snippet}"

    except Exception as e:
        return f"Fetch error for {url}: {e}"


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

def _parse_finish(args: dict) -> tuple[CompanyProfileDraft, NewsDraft]:
    profile = CompanyProfileDraft(**args["profile"])
    news = NewsDraft(**args["news"])
    return profile, news


async def _force_finish(messages: list[dict]) -> tuple[CompanyProfileDraft, NewsDraft]:
    """Force the agent to call finish() after the step cap is reached."""
    messages.append({
        "role": "user",
        "content": "You have reached the research step limit. You must call finish() now with whatever you have gathered so far.",
    })
    response = ai.chat.completions.create(
        model=OPENAI_MODEL,
        messages=messages,
        tools=TOOLS,
        tool_choice={"type": "function", "function": {"name": "finish"}},
    )
    args = json.loads(response.choices[0].message.tool_calls[0].function.arguments)
    return _parse_finish(args)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _initial_message(identity: IdentityDraft) -> str:
    return (
        f"Research this company and build a comprehensive profile.\n\n"
        f"Company identity:\n{identity.model_dump_json(indent=2)}"
    )


def _fmt_args(name: str, args: dict) -> str:
    if name == "search":
        return f'"{args.get("query", "")}"'
    if name == "fetch":
        url = args.get("url", "")
        return f'"{url[:70]}{"…" if len(url) > 70 else ""}"'
    return ""
