from __future__ import annotations

import json
from pathlib import Path
from typing import List

from rich.prompt import Confirm, Prompt
from rich.table import Table

from lib import ai_call_messages, console, output_dir, prompt, save_json
from models import IdentityDraft
from search import SearchProvider


def stage1_identity(company_input: str, searcher: SearchProvider) -> tuple[IdentityDraft, list[dict]]:
    """Resolve a company input to a verified identity using search-grounded LLM resolution.

    Returns the resolved identity and the full message history so the
    conversation can be continued if the user rejects the result.
    """
    console.rule("[bold blue]Stage 1: Identity Resolution")

    search_results = _search_results_block(company_input, searcher)

    history = [
        {"role": "system", "content": prompt("stage1_identity", "system")},
        {"role": "user", "content": prompt("stage1_identity", "user",
                                           company_input=company_input,
                                           search_results=search_results)},
    ]

    with console.status("Resolving company identity..."):
        data = ai_call_messages(history)

    history.append({"role": "assistant", "content": json.dumps(data)})
    return IdentityDraft(**data), history


def human_gate_identity(
    company_input: str,
    identity: IdentityDraft,
    history: list[dict],
    searcher: SearchProvider,
) -> tuple[IdentityDraft, Path]:
    """Show resolved identity, ask for confirmation, return (identity, outdir).

    On rejection, continues the existing conversation thread so the model
    has full context about what was wrong and why.
    """
    while True:
        _print_identity_table(identity)

        if Confirm.ask("Is this the correct company?"):
            break

        clarification = Prompt.ask("Please clarify (e.g. 'Apple Records, not Apple Inc.')")
        identity, history = _clarify_identity(clarification, history, searcher)

    outdir = output_dir(identity.resolved_name)
    save_json(outdir / "identity.json", identity)
    return identity, outdir


def _clarify_identity(
    clarification: str,
    history: list[dict],
    searcher: SearchProvider,
) -> tuple[IdentityDraft, list[dict]]:
    """Append a correction turn to the conversation and re-resolve."""
    search_results = _search_results_block(clarification, searcher)

    history.append({
        "role": "user",
        "content": (
            f'That\'s not the right company. User clarification: "{clarification}"\n\n'
            f"Fresh search results:\n{search_results}\n\n"
            "Please try again and return the corrected identity as JSON."
        ),
    })

    with console.status("Re-resolving company identity..."):
        data = ai_call_messages(history)

    history.append({"role": "assistant", "content": json.dumps(data)})
    return IdentityDraft(**data), history


def _search_results_block(query: str, searcher: SearchProvider) -> str:
    """Run two searches and format results as a numbered text block."""
    queries = [f'"{query}" company', f'"{query}" official website']
    lines: List[str] = []
    idx = 1
    for q in queries:
        try:
            for r in searcher.search(q, max_results=3):
                lines.append(f"{idx}. {r.title or '(no title)'}\n   URL: {r.url}\n   {r.snippet or ''}")
                idx += 1
        except Exception as e:
            console.print(f"  [yellow]Search failed for '{q}': {e}[/yellow]")

    return "\n\n".join(lines) if lines else "(no search results available)"


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
