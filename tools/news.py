from datetime import date, timedelta

import feedparser
import requests

from utils.text import clean_text

_UA = {"User-Agent": "NewsFactCheckAgent/0.2"}


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
        params = {"q": query, "language": "en", "pageSize": limit, "apiKey": api_key,
                  "sortBy": "publishedAt" if sort_by == "newest" else "relevancy"}
        if published_after:
            params["from"] = (published_after - timedelta(days=1)).isoformat()  # UTC; exact filter happens later
        if domains:
            params["domains"] = ",".join(domains)
        response = requests.get("https://newsapi.org/v2/everything", params=params, timeout=timeout)
        response.raise_for_status()
        return [
            {"title": clean_text(a.get("title")), "url": a.get("url", ""),
             "source": (a.get("source") or {}).get("name", ""), "published_at": a.get("publishedAt", ""),
             "description": clean_text(a.get("description"))}
            for a in response.json().get("articles", [])
        ]

    rss_query = query
    if domains:
        rss_query += " (" + " OR ".join(f"site:{d}" for d in domains) + ")"
    if published_after:
        rss_query += f" after:{published_after.isoformat()}"
    response = requests.get(
        "https://news.google.com/rss/search",
        params={"q": rss_query, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"},
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
