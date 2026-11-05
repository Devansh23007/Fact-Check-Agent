"""Reference search for encyclopedia and established factual knowledge (Wikipedia).

Provides authoritative historical, biographical, sports, scientific, and geographical
reference data with full article summaries and verifiable permanent URLs.
"""
import json
import re
import urllib.parse
import urllib.request

from utils.text import clean_text

_WIKI_HEADERS = {
    "User-Agent": "NewsFactCheckAgent/0.2 (newsroom-agent; factcheck@project.internal)"
}


def search_reference(query: str, *, timeout: int = 10, limit: int = 5) -> list[dict]:
    """Search Wikipedia for established factual records, history, records, and biographies."""
    clean_query = query.strip()
    if not clean_query:
        return []

    # 1. Search Wikipedia API for matching pages
    encoded = urllib.parse.quote(clean_query)
    search_url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={encoded}&utf8=&format=json"
    req = urllib.request.Request(search_url, headers=_WIKI_HEADERS)

    results = []
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            search_items = data.get("query", {}).get("search", [])[:limit]
    except Exception:
        return []

    for item in search_items:
        title = item.get("title", "")
        raw_snippet = re.sub(r"<[^>]+>", "", item.get("snippet", ""))
        snippet_clean = clean_text(
            raw_snippet.replace("&quot;", '"').replace("&#039;", "'").replace("&amp;", "&")
        )
        page_title_encoded = urllib.parse.quote(title.replace(" ", "_"))
        page_url = f"https://en.wikipedia.org/wiki/{page_title_encoded}"

        # 2. Try fetching the executive summary / extract from Wikipedia REST API
        extract = ""
        try:
            summary_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{page_title_encoded}"
            sreq = urllib.request.Request(summary_url, headers=_WIKI_HEADERS)
            with urllib.request.urlopen(sreq, timeout=min(timeout, 5)) as sresp:
                sdata = json.loads(sresp.read().decode("utf-8"))
                extract = clean_text(sdata.get("extract", ""))
        except Exception:
            pass

        # Combine key fact infobox snippet and executive summary
        parts = []
        if snippet_clean:
            parts.append(snippet_clean)
        if extract and extract not in snippet_clean:
            parts.append(extract)
        combined_snippet = " — ".join(parts) if parts else title

        results.append({
            "title": f"{title} - Wikipedia",
            "url": page_url,
            "source": "Wikipedia",
            "publisher": "Wikipedia",
            "snippet": combined_snippet[:800],
            "published_at": item.get("timestamp", ""),
        })

    return results
