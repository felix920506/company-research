from __future__ import annotations

import json
from pathlib import Path
from string import Template

from rich.prompt import Confirm, Prompt
from rich.table import Table

from lib import (
    MAX_IDENTITY_STEPS,
    OPENAI_MODEL,
    OPENAI_MODEL_IDENTITY,
    PROMPTS_DIR,
    ai_identity,
    api_call_with_retry,
    console,
    output_dir,
    save_json,
)
from models import IdentityDraft
from search import SearchProvider
from stages.research_agent import (
    _SEARCH_TOOL,
    _fmt_args,
    _log_cache_summary,
    _log_usage,
    _tool_search,
)

# ── Tool definitions ──────────────────────────────────────────────────────────

IDENTITY_TOOLS = [
    _SEARCH_TOOL,
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "Submit the resolved company identity.",
            "parameters": {
                "type": "object",
                "properties": {
                    "identity": {
                        "type": "object",
                        "description": "IdentityDraft fields",
                    },
                },
                "required": ["identity"],
            },
        },
    },
]

_MODEL = OPENAI_MODEL_IDENTITY or OPENAI_MODEL


# ── Entry point ───────────────────────────────────────────────────────────────

async def stage1_identity(
    company_input: str,
    searcher: SearchProvider,
) -> tuple[IdentityDraft, list[dict]]:
    """Resolve a company input to a verified identity using an agentic search loop.

    Returns the resolved identity and the full message history so the
    conversation can be continued if the user rejects the result.
    """
    console.rule("[bold blue]Stage 1: Identity Resolution")
    return await _run_identity_agent(company_input, searcher)


async def human_gate_identity(
    company_input: str,
    identity: IdentityDraft,
    history: list[dict],
    searcher: SearchProvider,
) -> tuple[IdentityDraft, Path]:
    """Show resolved identity, ask for confirmation, return (identity, outdir)."""
    while True:
        _print_identity_table(identity)

        if Confirm.ask("Is this the correct company?"):
            break

        clarification = Prompt.ask("Please clarify (e.g. 'Apple Records, not Apple Inc.')")
        identity, history = await _run_identity_agent(
            company_input, searcher, clarification=clarification
        )

    outdir = output_dir(identity.resolved_name)
    save_json(outdir / "identity.json", identity)
    return identity, outdir


# ── Agent loop ────────────────────────────────────────────────────────────────

async def _run_identity_agent(
    company_input: str,
    searcher: SearchProvider,
    clarification: str | None = None,
) -> tuple[IdentityDraft, list[dict]]:
    system_prompt = (PROMPTS_DIR / "stage1_identity.system.txt").read_text(encoding="utf-8")
    user_template = (PROMPTS_DIR / "stage1_identity.user.txt").read_text(encoding="utf-8")
    initial = Template(user_template).substitute(company_input=company_input)

    if clarification:
        initial += f'\n\nA previous attempt resolved the wrong company. User clarification: "{clarification}"'

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": initial},
    ]

    total_prompt_tokens = 0
    total_cached_tokens = 0

    for step in range(MAX_IDENTITY_STEPS):
        response = api_call_with_retry(lambda: ai_identity.chat.completions.create(
            model=_MODEL,
            messages=messages,
            tools=IDENTITY_TOOLS,
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

            console.print(f"  [dim]→ {name}[/dim]({_fmt_args(name, args)})  [dim](step {step + 1}/{MAX_IDENTITY_STEPS})[/dim]")

            if name == "finish":
                _log_cache_summary(total_prompt_tokens, total_cached_tokens)
                return _parse_identity(args), messages

            result = _tool_search(args["query"], searcher) if name == "search" else f"Unknown tool: {name}"

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })

    console.print(f"[yellow]Reached MAX_IDENTITY_STEPS ({MAX_IDENTITY_STEPS}) — forcing finish.[/yellow]")
    _log_cache_summary(total_prompt_tokens, total_cached_tokens)
    return await _force_finish_identity(messages), messages


async def _force_finish_identity(messages: list[dict]) -> IdentityDraft:
    messages.append({
        "role": "user",
        "content": "You have reached the step limit. Call finish() now with whatever you have.",
    })
    response = api_call_with_retry(lambda: ai_identity.chat.completions.create(
        model=_MODEL,
        messages=messages,
        tools=IDENTITY_TOOLS,
        tool_choice={"type": "function", "function": {"name": "finish"}},
    ))
    args = json.loads(response.choices[0].message.tool_calls[0].function.arguments)
    return _parse_identity(args)


# ── Finish handling ───────────────────────────────────────────────────────────

def _parse_identity(args: dict) -> IdentityDraft:
    try:
        data = args.get("identity", args)
        if data is args and "identity" not in args:
            console.print(
                f"  [yellow]finish() missing 'identity' key — attempting top-level parse[/yellow]\n"
                f"  keys present: {list(args.keys())}"
            )

        if not data or not data.get("resolved_name"):
            console.print("  [red bold]finish() returned empty identity — agent produced no output[/red bold]")
            return IdentityDraft(resolved_name="Unknown")

        # Strip null values from identifiers — model is Dict[str, str]
        if isinstance(data.get("identifiers"), dict):
            data["identifiers"] = {k: v for k, v in data["identifiers"].items() if v is not None}

        return IdentityDraft(**data)

    except Exception as e:
        console.print(f"  [red]_parse_identity failed: {e}[/red]\n  raw args: {json.dumps(args, indent=2, default=str)[:2000]}")
        raise


# ── Display ───────────────────────────────────────────────────────────────────

def _print_identity_table(identity: IdentityDraft) -> None:
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
