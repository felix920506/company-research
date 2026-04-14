from __future__ import annotations

from lib import MAX_LOOP_ITERATIONS, ai_call, console, prompt
from models import CompanyProfileDraft, FeedbackResult, NewsDraft


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
