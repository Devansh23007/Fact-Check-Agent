from urllib.parse import urljoin

import requests
import trafilatura

from agent.guardrails import validate_public_https_url

_UA = {"User-Agent": "Mozilla/5.0 (compatible; NewsFactCheckAgent/0.2)"}
_MAX_REDIRECTS = 5
_MAX_BYTES = 3_000_000


def fetch_page(url: str, *, max_chars: int = 4000, timeout: int = 20, resolver=None, session=None) -> dict:
    """Download a page and extract its main text.

    Every hop (including redirects to the publisher's own domain) must be HTTPS and resolve to a
    public IP address, so a malicious link cannot make the agent call localhost or your LAN.
    """
    http = session or requests
    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        validate_public_https_url(current, resolver)
        response = http.get(current, headers=_UA, timeout=timeout, allow_redirects=False)
        if response.status_code in (301, 302, 303, 307, 308) and response.headers.get("Location"):
            current = urljoin(current, response.headers["Location"])
            continue
        response.raise_for_status()
        break
    else:
        raise ValueError("Too many redirects")

    content_type = response.headers.get("Content-Type", "")
    if content_type and not any(t in content_type for t in ("html", "text/plain", "xml")):
        raise ValueError(f"Unsupported content type: {content_type.split(';')[0]}")
    if len(response.content) > _MAX_BYTES:
        raise ValueError("Page is too large")

    text = trafilatura.extract(response.text, include_comments=False, include_tables=False) or ""
    title = ""
    try:
        meta = trafilatura.extract_metadata(response.text)
        title = (meta.title or "") if meta else ""
    except Exception:
        pass
    return {"url": current, "title": title, "text": text[:max_chars]}
