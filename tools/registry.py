"""Tool schemas + dispatch. Every tool returns compact JSON and never raises."""
import json
import re
from datetime import date
from zoneinfo import ZoneInfo

from agent.guardrails import hostname
from agent.sources import SourceRegistry
from tools.docs_search import DocsIndex
from tools.factcheck import search_factchecks
from tools.news import search_news
from tools.scraper import fetch_page
from utils.cache import DiskCache
from utils.dates import parse_iso_date, published_date

MAX_RESULTS = 6

_DROP_WORDS = {
    "a", "an", "the", "of", "to", "in", "on", "for", "and", "or", "is", "are", "was", "were", "did", "does", "do",
    "has", "have", "had", "this", "that", "these", "those", "week", "today", "now", "new", "latest", "news", "recent",
    "approve", "approves", "approved", "approval", "announce", "announces", "announced", "say", "says", "said",
    "january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november",
    "december", "2024", "2025", "2026", "2027",
}


def query_terms(query: str) -> list[str]:
    """Significant lowercase keywords of a query (no filler words, verbs of reporting, or dates), de-duplicated."""
    terms: list[str] = []
    for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*", query):
        w = word.lower()
        if w not in _DROP_WORDS and w not in terms:
            terms.append(w)
    return terms


def relax_query(query: str, max_terms: int = 4) -> str:
    """A shorter query for news APIs that require every word to match."""
    return " ".join(query_terms(query)[:max_terms])


_ELECTION_RE = re.compile(r"\b(mid[\s-]*terms?|elections?|senate|senator|governor|ballot)\b", re.I)
_US_CONTEXT_RE = re.compile(
    r"\b(?:u\.?s\.?a?\.?|united states|american|texas|florida|georgia|pennsylvania|"
    r"michigan|ohio|arizona|wisconsin|nevada|north carolina|new york|california)\b", re.I
)
_F1_RE = re.compile(r"\b(?:f1|formula\s*1|grand prix)\b", re.I)
_F1_TITLE_RE = re.compile(r"\b(?:champions?|championship|standings|title|drivers?|points|season)\b", re.I)


def relevant_for_query(query: str, item: dict) -> bool:
    """Reject obvious topic mismatches for election searches while keeping generic search flexible."""
    text = " ".join(str(item.get(field) or "") for field in ("title", "description", "source"))
    if re.search(r"\b(?:f1|formula\s*1)\b", query, re.I):
        has_racing_context = bool(_F1_RE.search(text))
        asks_about_title = bool(re.search(r"champion|championship|world title|winner|standings", query, re.I))
        return has_racing_context and (not asks_about_title or bool(_F1_TITLE_RE.search(text)))
    us_election_query = bool(
        re.search(r"\bmid[\s-]*terms?\b", query, re.I)
        or (_US_CONTEXT_RE.search(query) and _ELECTION_RE.search(query))
    )
    if us_election_query:
        return bool(_ELECTION_RE.search(text) and _US_CONTEXT_RE.search(text))
    return True

SUBMIT_REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "2-4 plain-language sentences on what the research found."},
        "verdicts": {
            "type": "array",
            "description": "One entry per distinct checkable claim (max 3).",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "verdict": {"type": "string", "enum": ["supported", "contradicted", "misleading", "unverified"]},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "url": {"type": "string", "description": "Exact URL returned by a tool."},
                                "stance": {"type": "string", "enum": ["supports", "contradicts", "neutral"]},
                                "excerpt": {"type": "string", "description": "Words copied exactly from that source's text (max 40 words)."},
                            },
                            "required": ["url", "stance", "excerpt"],
                        },
                    },
                    "notes": {"type": "string", "description": "Caveats: developing story, conflicting sources, missing primary source."},
                },
                "required": ["claim", "verdict", "confidence", "evidence"],
            },
        },
    },
    "required": ["summary", "verdicts"],
}


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {"name": name, "description": description,
                                            "parameters": {"type": "object", "properties": properties, "required": required}}}


class ToolBox:
    def __init__(self, settings, registry: SourceRegistry, *, cache: DiskCache | None = None,
                 docs: DocsIndex | None = None, news_fn=search_news, factcheck_fn=search_factchecks,
                 fetch_fn=fetch_page, log=lambda message: None) -> None:
        self.settings, self.registry, self.cache, self.docs = settings, registry, cache, docs
        self.news_fn, self.factcheck_fn, self.fetch_fn, self.log = news_fn, factcheck_fn, fetch_fn, log
        self.tz = ZoneInfo(settings.timezone)
        self._searched_news: set = set()   # normalised news searches already run (blocks repeats)
        self.bulky_ids: set[str] = set()  # tool-call ids whose (large) output may be trimmed later

    # ---- schemas -------------------------------------------------------------------------
    def schemas(self) -> list[dict]:
        tools = [
            _fn("search_news",
                "Search recent news articles. Returns title, publisher, date, snippet and URL for up to 6 results. "
                "Use published_after for time-bound claims and domains to target official or primary sources.",
                {"query": {"type": "string", "description": "2-4 plain keywords, e.g. 'cabinet semiconductor policy'. The news API needs ALL words to appear, so extra words, dates and verbs like 'approves' often cause zero results."},
                 "published_after": {"type": "string", "description": "YYYY-MM-DD. Only articles on/after this date."},
                 "domains": {"type": "array", "items": {"type": "string"}, "description": "Restrict to these domains, e.g. ['pib.gov.in']."},
                 "sort_by": {"type": "string", "enum": ["relevancy", "newest"]}}, ["query"]),
            _fn("search_factchecks",
                "Look up published fact-checks (Google Fact Check Tools) of claims similar to the query.",
                {"query": {"type": "string"}}, ["query"]),
            _fn("fetch_page",
                "Read the main text of an article returned by a search tool. Only URLs from earlier search results are allowed. Do not call this on Google News redirect links (news.google.com) as they cannot be read; rely on search_news snippets instead.",
                {"url": {"type": "string"}}, ["url"]),
        ]
        if self.docs:
            tools.append(_fn("search_docs", "Search the user's own local documents for passages relevant to the claim.",
                             {"query": {"type": "string"}}, ["query"]))
        tools.append(_fn("submit_report",
                         "Submit the final fact-check. Call this exactly once, when research is finished. Cite only URLs returned by tools.",
                         SUBMIT_REPORT_SCHEMA["properties"], SUBMIT_REPORT_SCHEMA["required"]))
        return tools

    # ---- dispatch ------------------------------------------------------------------------
    def call(self, name: str, raw_args: str, call_id: str = "") -> tuple[str, str]:
        """Return (json_result, short_summary_for_the_research_log)."""
        try:
            args = json.loads(raw_args) if raw_args and raw_args.strip() else {}
            if not isinstance(args, dict):
                raise ValueError("arguments must be a JSON object")
        except (json.JSONDecodeError, ValueError) as exc:
            return json.dumps({"error": f"Invalid arguments: {exc}"}), "invalid arguments"
        handler = {"search_news": self._search_news, "search_factchecks": self._search_factchecks,
                   "fetch_page": self._fetch_page, "search_docs": self._search_docs}.get(name)
        if handler is None or (name == "search_docs" and not self.docs):
            return json.dumps({"error": f"Unknown tool: {name}"}), "unknown tool"
        try:
            result, summary = handler(args)
        except Exception as exc:  # tool failures are information for the model, not crashes
            status = getattr(getattr(exc, "response", None), "status_code", None)
            msg = f"{type(exc).__name__}" + (f" (HTTP {status})" if status else f": {str(exc)[:120]}")
            return json.dumps({"error": f"{name} failed: {msg}. Try a different query or source."}), f"failed: {msg}"
        if name in ("fetch_page", "search_docs") and call_id:
            self.bulky_ids.add(call_id)
        return json.dumps(result, ensure_ascii=False), summary

    def _cached(self, namespace: str, params: dict, producer):
        return self.cache.get_or_set(namespace, params, producer) if self.cache else producer()

    # ---- tools ---------------------------------------------------------------------------
    def _news(self, query: str, after, domains, sort_by: str) -> list[dict]:
        params = {"q": query, "after": str(after), "domains": domains, "sort": sort_by, "newsapi": bool(self.settings.newsapi_key)}
        return self._cached("news", params, lambda: self.news_fn(
            query, api_key=self.settings.newsapi_key, timeout=self.settings.request_timeout, limit=10,
            published_after=after, domains=domains, sort_by=sort_by))

    def _search_news(self, a: dict):
        query = str(a.get("query", "")).strip()
        if not query:
            return {"error": "query is required"}, "missing query"
        after = parse_iso_date(a.get("published_after"))
        domains = [d.lower() for d in (a.get("domains") or []) if isinstance(d, str) and re.fullmatch(r"[a-zA-Z0-9.-]+", d)] or None
        sort_by = "newest" if a.get("sort_by") == "newest" else "relevancy"

        signature = (frozenset(query_terms(query)), tuple(domains or ()))
        if signature in self._searched_news:
            return ({"results": [], "note": "You already ran an equivalent search. Do not repeat it: read an article with fetch_page, "
                                            "try search_factchecks, use clearly different keywords or domains, or call submit_report."},
                    "duplicate search skipped")
        self._searched_news.add(signature)

        found = self._news(query, after, domains, sort_by)
        relaxed_note = ""
        if not found:
            relaxed = relax_query(query)
            if relaxed and (relaxed != query.lower() or after):
                # Many news APIs need every word to match and cover only a limited window: retry once with
                # fewer keywords and no server-side date limit (the date window is still applied below).
                found = self._news(relaxed, None, domains, sort_by)
                relaxed_note = f"The full query matched nothing, so it was simplified to '{relaxed}'" + (" and the date limit was applied locally. " if after else ". ")

        results, seen, too_old, irrelevant = [], set(), 0, 0
        for item in found:
            if not relevant_for_query(query, item):
                irrelevant += 1
                continue
            key = item.get("url") or item.get("title", "").strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            when = published_date(item.get("published_at", ""), self.tz)
            if after and when and when < after:
                too_old += 1
                continue
            source = self.registry.add(item.get("url", ""), title=item.get("title", ""), publisher=item.get("source", ""),
                                       kind="news_article", published_at=item.get("published_at", ""),
                                       snippet=(item.get("description") or "")[:400])
            if source is None:
                continue
            results.append({"url": source.url, "title": source.title, "publisher": source.publisher,
                            "published_at": source.published_at, "snippet": source.snippet[:250], "tier": source.tier,
                            "readable": hostname(source.url) != "news.google.com"})
            if len(results) >= MAX_RESULTS:
                break

        if results:
            note = relaxed_note.strip()
        elif too_old:
            note = (relaxed_note + f"Found {too_old} article(s) on this topic, but all were published before {after}. Coverage inside your date "
                    "window may not exist yet (news APIs can lag by a day). That is not evidence the claim is false; say so in the report.")
        else:
            note = (relaxed_note + (f"Discarded {irrelevant} result(s) that did not match the election topic. " if irrelevant else "")
                    + "No usable results. Try different, shorter keywords or remove the domain filter. "
                    "Absence of results is not evidence a claim is false. After two empty searches, move on to search_factchecks or submit_report.")
        summary = f"{len(results)} result(s)" + (f", {irrelevant} unrelated discarded" if irrelevant else "") + (f", {too_old} too old" if too_old else "") + (" (query simplified)" if relaxed_note else "")
        return {"results": results, "filtered_out_by_date": too_old, "note": note}, summary

    def _search_factchecks(self, a: dict):
        query = str(a.get("query", "")).strip()
        if not query:
            return {"error": "query is required"}, "missing query"
        if not self.settings.google_factcheck_api_key:
            return {"results": [], "note": "Fact-check search is not configured (GOOGLE_FACTCHECK_API_KEY missing)."}, "not configured"
        found = self._cached("factcheck", {"q": query}, lambda: self.factcheck_fn(
            query, api_key=self.settings.google_factcheck_api_key, timeout=self.settings.request_timeout, limit=MAX_RESULTS))
        results = []
        for item in found[:MAX_RESULTS]:
            source = self.registry.add(item.get("url", ""), title=item.get("title", ""), publisher=item.get("publisher", ""),
                                       kind="published_fact_check", rating=item.get("rating", ""),
                                       claim_reviewed=item.get("claim", ""), published_at=item.get("review_date", ""))
            if source:
                results.append({"url": source.url, "publisher": source.publisher, "claim_reviewed": source.claim_reviewed,
                                "rating": source.rating, "title": source.title})
        note = "" if results else "No published fact-checks found for this wording; that does not mean the claim is true or false."
        return {"results": results, "note": note}, f"{len(results)} review(s)"

    def _fetch_page(self, a: dict):
        url = str(a.get("url", "")).strip()
        source = self.registry.get(url)
        if source is None:
            source = self.registry.resolve_registered_prefix(url)
        if source is None:
            registered = [item.url for item in self.registry.all() if item.url][:8]
            return ({"error": "That URL did not uniquely match a registered search result. Fetch only exact URLs from search results.",
                     "registered_urls": registered}, "rejected unknown or ambiguous URL")
        if hostname(source.url) == "news.google.com":
            return {"error": "Google News redirect links cannot be read. Do not call fetch_page on them. Rely on the headline and snippet already returned by search_news, or call submit_report."}, "unreadable redirect link"
        page = self._cached("page", {"url": source.url, "n": self.settings.max_page_chars}, lambda: self.fetch_fn(
            source.url, max_chars=self.settings.max_page_chars, timeout=min(self.settings.request_timeout, 15)))
        final_url = page.get("url") or source.url
        self.registry.alias(source.url, final_url)
        text = page.get("text", "")
        self.registry.add(source.url, article_text=text, title=page.get("title", "") if not source.title else "")
        if not text:
            return {"url": source.url, "text": "", "note": "No readable text (paywall, login wall or script-rendered page). Rely on the snippet or find another source."}, "no readable text"
        return {"url": source.url, "title": source.title, "text": text}, f"read {len(text)} chars"

    def _search_docs(self, a: dict):
        query = str(a.get("query", "")).strip()
        if not query:
            return {"error": "query is required"}, "missing query"
        results = []
        for hit in self.docs.search(query, k=4):
            self.registry.add(hit["url"], title=hit["source"], publisher=hit["source"], kind="document", article_text=hit["text"])
            results.append({"url": hit["url"], "document": hit["source"], "text": hit["text"]})
        note = "" if results else "No matching passages in the local documents."
        return {"results": results, "note": note}, f"{len(results)} passage(s)"
