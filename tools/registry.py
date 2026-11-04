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
        self.bulky_ids: set[str] = set()  # tool-call ids whose (large) output may be trimmed later

    # ---- schemas -------------------------------------------------------------------------
    def schemas(self) -> list[dict]:
        tools = [
            _fn("search_news",
                "Search recent news articles. Returns title, publisher, date, snippet and URL for up to 6 results. "
                "Use published_after for time-bound claims and domains to target official or primary sources.",
                {"query": {"type": "string", "description": "3-7 keywords, no question words."},
                 "published_after": {"type": "string", "description": "YYYY-MM-DD. Only articles on/after this date."},
                 "domains": {"type": "array", "items": {"type": "string"}, "description": "Restrict to these domains, e.g. ['pib.gov.in']."},
                 "sort_by": {"type": "string", "enum": ["relevancy", "newest"]}}, ["query"]),
            _fn("search_factchecks",
                "Look up published fact-checks (Google Fact Check Tools) of claims similar to the query.",
                {"query": {"type": "string"}}, ["query"]),
            _fn("fetch_page",
                "Read the main text of an article returned by a search tool. Only URLs from earlier search results are allowed.",
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
    def _search_news(self, a: dict):
        query = str(a.get("query", "")).strip()
        if not query:
            return {"error": "query is required"}, "missing query"
        after = parse_iso_date(a.get("published_after"))
        domains = [d.lower() for d in (a.get("domains") or []) if isinstance(d, str) and re.fullmatch(r"[a-zA-Z0-9.-]+", d)] or None
        sort_by = "newest" if a.get("sort_by") == "newest" else "relevancy"
        params = {"q": query, "after": str(after), "domains": domains, "sort": sort_by, "newsapi": bool(self.settings.newsapi_key)}
        found = self._cached("news", params, lambda: self.news_fn(
            query, api_key=self.settings.newsapi_key, timeout=self.settings.request_timeout, limit=10,
            published_after=after, domains=domains, sort_by=sort_by))

        results, seen, too_old = [], set(), 0
        for item in found:
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
        note = "" if results else "No results. Try other keywords or remove the date/domain filter. Absence of results is not evidence a claim is false."
        return {"results": results, "filtered_out_by_date": too_old, "note": note}, f"{len(results)} result(s)" + (f", {too_old} too old" if too_old else "")

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
            return {"error": "That URL was not returned by a search tool. Fetch only URLs from search results."}, "rejected unknown URL"
        if hostname(source.url) == "news.google.com":
            return {"error": "Google News redirect links cannot be read. Use the snippet, or search for the publisher's own URL."}, "unreadable redirect link"
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
