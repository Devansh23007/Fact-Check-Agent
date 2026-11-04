from typing import Literal

from pydantic import BaseModel, Field

Stance = Literal["supports", "contradicts", "neutral"]
VerdictLabel = Literal["supported", "contradicted", "unverified", "misleading"]
Confidence = Literal["low", "medium", "high"]


# ---- What the model submits (submit_report tool arguments) -------------------------------
class EvidenceDraft(BaseModel):
    url: str
    stance: Stance
    excerpt: str = ""


class VerdictDraft(BaseModel):
    claim: str
    verdict: VerdictLabel
    confidence: Confidence
    evidence: list[EvidenceDraft] = Field(default_factory=list)
    notes: str = ""


class ReportDraft(BaseModel):
    summary: str
    verdicts: list[VerdictDraft] = Field(min_length=1)


# ---- What we save (after code-level verification) ----------------------------------------
class Evidence(BaseModel):
    source_name: str
    url: str
    stance: Stance
    excerpt: str
    excerpt_verified: bool = False      # excerpt found in the text we actually retrieved
    source_tier: str = "general"        # official | fact_checker | established | document | general
    published_at: str = ""


class Verdict(BaseModel):
    claim: str
    verdict: VerdictLabel
    confidence: Confidence
    evidence: list[Evidence] = Field(default_factory=list)
    notes: str = ""


class SourceSummary(BaseModel):
    title: str
    url: str
    publisher: str = ""
    published_at: str = ""
    tier: str = "general"
    read_full_text: bool = False


class ResearchStep(BaseModel):
    step: int
    tool: str
    arguments: dict = Field(default_factory=dict)
    summary: str = ""


class FactCheckReport(BaseModel):
    topic: str
    generated_at: str = ""
    model: str = ""
    summary: str
    verdicts: list[Verdict] = Field(default_factory=list)
    sources_considered: list[SourceSummary] = Field(default_factory=list)
    research_log: list[ResearchStep] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
