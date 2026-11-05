"""Code-level checks applied to whatever the model submits.

The prompt asks the model to behave; this module makes sure the saved report is honest
even if it doesn't: unknown URLs are removed, quotes are checked against the retrieved text,
and confidence is capped by the strength of the evidence.
"""
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher

from agent.guardrails import hostname
from agent.reliability import DEEP_TIERS
from agent.schemas import (Evidence, FactCheckReport, ReportDraft, ResearchStep, SourceSummary, Verdict)
from agent.sources import SourceRegistry

_DIRECTION = {"supported": "supports", "contradicted": "contradicts"}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def excerpt_matches(excerpt: str, source_text: str, threshold: float = 0.7) -> bool:
    """True if a long contiguous run of the excerpt's words appears in the source text."""
    ex, src = _words(excerpt), _words(source_text)
    if len(ex) < 3 or not src:
        return False
    match = SequenceMatcher(None, ex, src, autojunk=False).find_longest_match(0, len(ex), 0, len(src))
    return match.size / len(ex) >= threshold


def source_summaries(registry: SourceRegistry) -> list[SourceSummary]:
    return [
        SourceSummary(title=s.title or s.claim_reviewed or s.url, url=s.url, publisher=s.publisher,
                      published_at=s.published_at, tier=s.tier, read_full_text=s.has_full_text,
                      snippet=s.snippet)
        for s in registry.all()
    ]


def _meta(topic: str, model: str) -> dict:
    return {"topic": topic, "model": model, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def finalize(topic: str, draft: ReportDraft, registry: SourceRegistry, research_log: list[ResearchStep],
             model: str, warnings: list[str] | None = None) -> FactCheckReport:
    verdicts: list[Verdict] = []
    for item in draft.verdicts:
        evidence: list[Evidence] = []
        dropped = 0
        for e in item.evidence:
            source = registry.get(e.url)
            if source is None:
                dropped += 1
                continue
            evidence.append(Evidence(
                source_name=source.publisher or hostname(source.url) or "Unknown source",
                url=source.url, stance=e.stance, excerpt=e.excerpt.strip()[:600],
                excerpt_verified=excerpt_matches(e.excerpt, source.searchable_text()),
                source_tier=source.tier, published_at=source.published_at,
            ))

        verdict, confidence = item.verdict, item.confidence
        notes = [item.notes.strip()] if item.notes.strip() else []
        if dropped:
            notes.append(f"{dropped} cited URL(s) were not returned by any tool and were removed.")

        verified = [e for e in evidence if e.excerpt_verified]
        if not evidence:
            verdict, confidence = "unverified", "low"
            notes.append("No retrieved source supports this assessment.")
        else:
            wanted = _DIRECTION.get(verdict)
            if wanted and not any(e.stance == wanted for e in evidence):
                verdict, confidence = "unverified", "low"
                notes.append("The cited evidence does not point the way the verdict claimed, so it was reset to unverified.")
            elif verdict != "unverified" and not verified:
                confidence = "low"
                notes.append("None of the quoted excerpts could be matched to the retrieved text, so confidence was capped at low.")

        if verdict != "unverified" and confidence != "low":
            deep = any(e.source_tier in DEEP_TIERS or (registry.get(e.url) and registry.get(e.url).has_full_text) for e in verified)
            independent = {hostname(e.url) for e in verified if e.stance != "neutral"}
            if confidence == "high" and (len(independent) < 2 or not deep):
                confidence = "medium"
                notes.append("Confidence reduced from high: needs two independent verified sources, one with full text, an official source, or a published fact-check.")
            if confidence == "medium" and not deep:
                confidence = "low"
                notes.append("Confidence reduced: only headlines or snippets were available.")

        verdicts.append(Verdict(claim=item.claim, verdict=verdict, confidence=confidence,
                                evidence=evidence, notes=" ".join(notes)))

    return FactCheckReport(summary=draft.summary, verdicts=verdicts, sources_considered=source_summaries(registry),
                           research_log=research_log, warnings=warnings or [], **_meta(topic, model))


def fallback_report(topic: str, registry: SourceRegistry, research_log: list[ResearchStep], reason: str,
                    model: str) -> FactCheckReport:
    """Transparent 'unverified' report when the model could not finish."""
    evidence = [
        Evidence(source_name=s.publisher or hostname(s.url), url=s.url, stance="neutral",
                 excerpt=(f"{s.title}. {s.snippet}" if s.snippet else s.title)[:500],
                 excerpt_verified=True,   # copied directly from the retrieved headline/snippet
                 source_tier=s.tier, published_at=s.published_at)
        for s in registry.all()[:6]
    ]
    note = ("These sources were retrieved but not assessed. This does not show the claim is false."
            if evidence else "No sources were retrieved. This does not show the claim is false.")
    return FactCheckReport(
        summary=reason,
        verdicts=[Verdict(claim=topic.rstrip("? .") or topic, verdict="unverified", confidence="low",
                          evidence=evidence, notes=note)],
        sources_considered=source_summaries(registry), research_log=research_log, warnings=[reason],
        **_meta(topic, model),
    )