from __future__ import annotations

from pathlib import Path

from rich.prompt import Confirm, Prompt
from rich.table import Table

from lib import ai_call, console, output_dir, prompt, save_json
from models import IdentityDraft


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
    while True:
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

        if Confirm.ask("Is this the correct company?"):
            break

        clarification = Prompt.ask("Please clarify (e.g. 'Apple Records, not Apple Inc.')")
        identity = stage1_identity(clarification)

    outdir = output_dir(identity.resolved_name)
    save_json(outdir / "identity.json", identity)
    return identity, outdir
