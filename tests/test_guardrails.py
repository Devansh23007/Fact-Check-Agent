import pytest

from agent.guardrails import normalize_url, validate_public_https_url
from agent.sources import SourceRegistry


def test_normalize_ignores_tracking_fragment_slash_and_case():
    a = normalize_url("https://Example.com/story/?utm_source=x&id=5#top")
    b = normalize_url("https://example.com/story?id=5")
    assert a == b


def test_registry_matches_equivalent_urls():
    reg = SourceRegistry()
    reg.add("https://news.example.com/a/", title="A")
    assert reg.get("https://news.example.com/a?utm_campaign=z").title == "A"
    assert reg.get("https://evil.example.com/a") is None


def test_registry_alias_after_redirect():
    reg = SourceRegistry()
    reg.add("https://short.example/x", title="T")
    reg.alias("https://short.example/x", "https://publisher.example/full")
    assert reg.get("https://publisher.example/full").title == "T"


def test_registry_never_blanks_existing_fields():
    reg = SourceRegistry()
    reg.add("https://a.example/1", title="Title", article_text="body")
    reg.add("https://a.example/1", title="", snippet="s")
    s = reg.get("https://a.example/1")
    assert s.title == "Title" and s.article_text == "body" and s.snippet == "s"


@pytest.mark.parametrize("url", ["http://example.com", "https://127.0.0.1/x", "https://10.0.0.5/", "https://[::1]/"])
def test_blocks_non_https_and_private_literals(url):
    with pytest.raises(ValueError):
        validate_public_https_url(url)


def test_blocks_hostname_resolving_to_private_ip():
    with pytest.raises(ValueError):
        validate_public_https_url("https://sneaky.example/", resolver=lambda h: ["192.168.1.10"])


def test_allows_public_host():
    assert validate_public_https_url("https://example.com/a", resolver=lambda h: ["93.184.216.34"])
