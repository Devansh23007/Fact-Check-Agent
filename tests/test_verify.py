from agent.schemas import EvidenceDraft, ReportDraft, VerdictDraft
from agent.sources import SourceRegistry
from agent.verify import excerpt_matches, finalize

ARTICLE = ("The Union Cabinet on Tuesday approved the new national semiconductor policy with an outlay of "
           "ten thousand crore rupees to support domestic chip fabrication.")


def _registry():
    reg = SourceRegistry()
    reg.add("https://pib.gov.in/a", title="Cabinet approves policy", publisher="PIB", article_text=ARTICLE)
    reg.add("https://news-one.example/a", title="Cabinet approves chip policy", publisher="One", article_text=ARTICLE)
    reg.add("https://news-two.example/b", title="Chip policy cleared", publisher="Two", snippet="Cabinet approved the chip policy")
    return reg


def _draft(verdict="supported", confidence="high", evidence=None):
    return ReportDraft(summary="s", verdicts=[VerdictDraft(claim="c", verdict=verdict, confidence=confidence, evidence=evidence or [])])


def test_excerpt_matching():
    assert excerpt_matches("approved the new national semiconductor policy", ARTICLE)
    assert not excerpt_matches("the prime minister resigned on Monday evening", ARTICLE)
    assert not excerpt_matches("ok", ARTICLE)


def test_fabricated_url_is_removed_and_verdict_reset():
    report = finalize("t", _draft(evidence=[EvidenceDraft(url="https://made-up.example/x", stance="supports", excerpt="anything here")]),
                      _registry(), [], "m")
    v = report.verdicts[0]
    assert v.verdict == "unverified" and v.confidence == "low" and not v.evidence
    assert "removed" in v.notes


def test_high_confidence_kept_with_two_verified_independent_sources():
    ev = [EvidenceDraft(url="https://pib.gov.in/a", stance="supports", excerpt="approved the new national semiconductor policy"),
          EvidenceDraft(url="https://news-one.example/a/?utm_source=x", stance="supports", excerpt="approved the new national semiconductor policy")]
    v = finalize("t", _draft(evidence=ev), _registry(), [], "m").verdicts[0]
    assert v.verdict == "supported" and v.confidence == "high"
    assert all(e.excerpt_verified for e in v.evidence)


def test_high_downgraded_when_only_one_independent_source():
    ev = [EvidenceDraft(url="https://news-one.example/a", stance="supports", excerpt="approved the new national semiconductor policy")]
    v = finalize("t", _draft(evidence=ev), _registry(), [], "m").verdicts[0]
    assert v.confidence in ("medium", "low") and v.confidence != "high"


def test_snippet_only_evidence_is_capped_at_low():
    ev = [EvidenceDraft(url="https://news-two.example/b", stance="supports", excerpt="Cabinet approved the chip policy")]
    v = finalize("t", _draft(confidence="medium", evidence=ev), _registry(), [], "m").verdicts[0]
    assert v.confidence == "low"


def test_unmatched_quote_caps_confidence():
    ev = [EvidenceDraft(url="https://pib.gov.in/a", stance="supports", excerpt="The government banned all chip imports immediately")]
    v = finalize("t", _draft(evidence=ev), _registry(), [], "m").verdicts[0]
    assert v.confidence == "low" and not v.evidence[0].excerpt_verified


def test_stance_must_match_verdict_direction():
    ev = [EvidenceDraft(url="https://pib.gov.in/a", stance="contradicts", excerpt="approved the new national semiconductor policy")]
    v = finalize("t", _draft(verdict="supported", evidence=ev), _registry(), [], "m").verdicts[0]
    assert v.verdict == "unverified"
