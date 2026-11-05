from agent.schemas import FactCheckReport

_ICON = {"supported": "✅", "contradicted": "❌", "misleading": "⚠️", "unverified": "❓"}


def to_markdown(report: FactCheckReport) -> str:
    lines = [f"# Fact-check: {report.topic}", "", f"_Generated {report.generated_at} · model `{report.model}`_", "", report.summary, ""]
    if report.llm_calls:
        lines += ["**AI calls served by:** " + ", ".join(f"{provider}: {count}" for provider, count in report.llm_calls.items()), ""]
    for i, verdict in enumerate(report.verdicts, 1):
        lines += [
            f"## {i}. {verdict.claim}",
            f"**{_ICON.get(verdict.verdict, '')} {verdict.verdict.upper()}** · confidence: **{verdict.confidence}**",
            "",
        ]
        if verdict.notes:
            lines += [verdict.notes, ""]
        for ev in verdict.evidence:
            mark = "verified quote" if ev.excerpt_verified else "quote NOT matched to source text"
            lines.append(f"- **{ev.stance}** — [{ev.source_name}]({ev.url}) ({ev.source_tier}, {mark})")
            if ev.excerpt:
                lines.append(f"  > {ev.excerpt}")
        lines.append("")
    if report.warnings:
        lines += ["## Warnings", *[f"- {w}" for w in report.warnings], ""]
    lines += ["## Sources considered", ""]
    for s in report.sources_considered:
        full = "full text read" if s.read_full_text else "headline/snippet only"
        lines.append(f"- [{s.title or s.url}]({s.url}) — {s.publisher or 'unknown'}, {s.published_at or 'date unknown'}, {s.tier}, {full}")
    lines += ["", "## Research steps", ""]
    for step in report.research_log:
        lines.append(f"{step.step}. `{step.tool}` {step.arguments} → {step.summary}")
    lines += ["", "_Automated research aid. Review the sources before relying on any verdict, especially for developing stories._", ""]
    return "\n".join(lines)
