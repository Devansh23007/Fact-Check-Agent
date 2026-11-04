"""URL safety and normalisation.

validate_public_https_url blocks requests to localhost / private networks (SSRF).
normalize_url makes URL comparison stable, so a cited URL that differs only by a
trailing slash, tracking parameter or fragment still matches the URL a tool returned.
"""
import ipaddress
import socket
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_TRACKING = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src", "igshid"}


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme == "doc":  # local document citations, e.g. doc://report.pdf#3
        return url
    try:
        port = parsed.port
    except ValueError:
        port = None
    host = (parsed.hostname or "").lower()
    if port and port not in (80, 443):
        host = f"{host}:{port}"
    path = parsed.path or "/"
    if len(path) > 1:
        path = path.rstrip("/") or "/"
    query = [
        (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING
    ]
    return urlunparse((parsed.scheme.lower(), host, path, "", urlencode(query), ""))


def hostname(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _resolve(host: str) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, None)]


def validate_public_https_url(url: str, resolver: Callable[[str], list[str]] | None = None) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Only HTTPS URLs are allowed")
    try:
        addresses = [ipaddress.ip_address(parsed.hostname)]
    except ValueError:
        try:
            addresses = [ipaddress.ip_address(a.split("%")[0]) for a in (resolver or _resolve)(parsed.hostname)]
        except OSError as exc:
            raise ValueError(f"Could not resolve host: {parsed.hostname}") from exc
    if not addresses or any(not ip.is_global for ip in addresses):
        raise ValueError("URL points to a non-public network address")
    return url
