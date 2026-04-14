from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rich.markdown import Markdown
from rich.prompt import Confirm, Prompt

from lib import ai_call, console, prompt, save_json
from models import CompanyProfileDraft, IdentityDraft, NewsDraft


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


def _save_final(
    report_md: str,
    identity: IdentityDraft,
    profile: CompanyProfileDraft,
    news: NewsDraft,
    outdir: Path,
) -> None:
    (outdir / "final.md").write_text(report_md)
    save_json(outdir / "final.json", {
        "identity": identity.model_dump(),
        "profile": profile.model_dump(),
        "news": news.model_dump(),
        "report_md": report_md,
        "finalized_at": datetime.now().isoformat(),
    })
    console.print(f"\n[green]Saved:[/green] {outdir}/final.md  and  {outdir}/final.json")
