from datetime import date, timedelta
import re

import feedparser
import requests

from utils.text import clean_text

_UA = {"User-Agent": "NewsFactCheckAgent/0.2"}


def initial_news_query(topic: str) -> str:
    """Turn common question wording into a short, searchable headline query."""
    query = topic.strip()
    query = re.sub(
        r"^\s*(what is known about\s+(?:this|the)?\s*(?:story|claim|event|headline)?[:\s]*|"
        r"what do we know about\s+(?:this|the)?\s*(?:story|claim|event|headline)?[:\s]*|"
        r"what(?:'s|\s+is)\s+the\s+story\s+(?:about|behind)[:\s]*|"
        r"tell me about\s+(?:this|the)?\s*|"
        r"is\s+it\s+true\s+(?:that)?[:\s]*|"
        r"(?:any\s+)?(?:news|updates?)\s+(?:about|on)[:\s]*|"
        r"what(?:'s|\s+is)\s+happening\s+with[:\s]*)",
        "", query, flags=re.I
    ).strip()
    query = re.sub(r"\b(usa|united states of america|united states)\b", "US", query, flags=re.I)
    query = re.sub(r"\s+", " ", query).strip(" ?.,\"'")
    return query[:120] or topic[:120]


def initial_news_queries(topic: str) -> list[str]:
    """Provide a small synonym ladder for questions whose exact wording is uncommon."""
    query = initial_news_query(topic)
    lowered = query.lower()
    if re.search(r"\b(?:f1|formula\s*1)\b", lowered) and not re.search(r"\b(democrats|congress|senate|election|politics|biden|trump)\b", lowered):
        year = re.search(r"\b20\d{2}\b", topic)
        season = year.group(0) if year else str(date.today().year)
        if re.search(r"champion|championship|world title|world champion|winner", lowered):
            return [f"Formula 1 {season} champion", f"Formula 1 {season} standings", "F1 championship latest"]
        return [query, f"Formula 1 {season} standings"]
    return [query]


def search_news(
    query: str,
    *,
    api_key: str = "",
    timeout: int = 20,
    limit: int = 8,
    published_after: date | None = None,
    domains: list[str] | None = None,
    sort_by: str = "relevancy",       # relevancy | newest
) -> list[dict]:
    """NewsAPI when a key is set, otherwise Google News RSS.

    Note: Google News RSS links are redirect pages whose article text can't be read,
    so set NEWSAPI_KEY if you want the agent to read full articles.
    """
    if api_key:
        params = {"q": query, "language": "en", "pageSize": limit,
                  "sortBy": "publishedAt" if sort_by == "newest" else "relevancy"}
        if published_after:
            params["from"] = (published_after - timedelta(days=1)).isoformat()  # UTC; exact filter happens later
        if domains:
            params["domains"] = ",".join(domains)
        try:
            response = requests.get("https://newsapi.org/v2/everything", params=params,
                                    headers={"X-Api-Key": api_key}, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
            if payload.get("status") == "ok":
                articles = [
                    {"title": clean_text(a.get("title")), "url": a.get("url", ""),
                     "source": (a.get("source") or {}).get("name", ""), "published_at": a.get("publishedAt", ""),
                     "description": clean_text(a.get("description"))}
                    for a in payload.get("articles", [])
                ]
                if articles:
                    return articles
        except (requests.RequestException, ValueError):
            # Keep research usable when the NewsAPI key, plan, or quota is unavailable.
            pass

    rss_query = query
    if domains:
        rss_query += " (" + " OR ".join(f"site:{d}" for d in domains) + ")"
    if published_after:
        rss_query += f" after:{published_after.isoformat()}"
    is_us_topic = bool(re.search(r"\b(US|USA|America|midterm|Congress)\b", query, re.I))
    locale = {"hl": "en-US", "gl": "US", "ceid": "US:en"} if is_us_topic else {"hl": "en-IN", "gl": "IN", "ceid": "IN:en"}
    response = requests.get(
        "https://news.google.com/rss/search",
        params={"q": rss_query, **locale},
        headers=_UA, timeout=timeout,
    )
    response.raise_for_status()
    feed = feedparser.parse(response.content)
    return [
        {"title": clean_text(e.get("title")), "url": e.get("link", ""),
         "source": e.get("source", {}).get("title", "Google News RSS"),
         "published_at": e.get("published", ""), "description": clean_text(e.get("summary"))}
        for e in feed.entries[:limit]
    ]
