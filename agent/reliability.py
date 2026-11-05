"""Very small, editable source-tier list.

This is a heuristic to help weigh evidence, not a judgement on any outlet.
Extend the sets below to match the sources you trust.
"""
from agent.guardrails import hostname

OFFICIAL_SUFFIXES = (".gov", ".gov.in", ".nic.in", ".gov.uk", ".europa.eu", ".mil")
OFFICIAL_DOMAINS = {"who.int", "un.org", "worldbank.org", "imf.org", "rbi.org.in"}
FACT_CHECKERS = {
    "altnews.in", "boomlive.in", "factcheck.org", "snopes.com", "politifact.com", "factly.in",
    "vishvasnews.com", "newschecker.in", "fullfact.org", "factcheck.afp.com", "leadstories.com",
}
ESTABLISHED = {
    "reuters.com", "apnews.com", "bbc.com", "bbc.co.uk", "afp.com", "bloomberg.com", "ptinews.com",
    "wikipedia.org", "en.wikipedia.org",
}
DEEP_TIERS = {"official", "fact_checker", "document", "established"}


def classify(url: str, kind: str = "news_article") -> str:
    if kind == "published_fact_check":
        return "fact_checker"
    if kind == "document" or url.startswith("doc://"):
        return "document"
    if kind in ("reference", "encyclopedia"):
        return "established"
    host = hostname(url)
    if not host:
        return "general"
    if host in OFFICIAL_DOMAINS or host.endswith(OFFICIAL_SUFFIXES) or any(host.endswith("." + d) for d in OFFICIAL_DOMAINS):
        return "official"
    if any(host == d or host.endswith("." + d) for d in FACT_CHECKERS):
        return "fact_checker"
    if any(host == d or host.endswith("." + d) for d in ESTABLISHED):
        return "established"
    return "general"
