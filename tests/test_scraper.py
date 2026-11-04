import pytest

from tools.scraper import fetch_page

PUBLIC = lambda host: ["93.184.216.34"]


class Resp:
    def __init__(self, status=200, headers=None, text=""):
        self.status_code, self.headers, self.text, self.content = status, headers or {}, text, text.encode()

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class Session:
    def __init__(self, routes):
        self.routes, self.requested = routes, []

    def get(self, url, **kw):
        self.requested.append(url)
        assert kw.get("allow_redirects") is False
        return self.routes[url]


HTML = "<html><body><article><p>" + "The cabinet approved the policy on Tuesday. " * 20 + "</p></article></body></html>"


def test_follows_redirect_to_publisher_and_extracts_text():
    s = Session({"https://short.example/x": Resp(302, {"Location": "https://publisher.example/story"}),
                 "https://publisher.example/story": Resp(200, {"Content-Type": "text/html"}, HTML)})
    page = fetch_page("https://short.example/x", resolver=PUBLIC, session=s)
    assert page["url"] == "https://publisher.example/story" and "cabinet approved" in page["text"]


def test_redirect_to_private_address_is_blocked():
    s = Session({"https://short.example/x": Resp(302, {"Location": "https://internal.example/admin"})})
    with pytest.raises(ValueError):
        fetch_page("https://short.example/x", resolver=lambda h: ["10.0.0.1"] if h == "internal.example" else ["93.184.216.34"], session=s)
    assert s.requested == ["https://short.example/x"]


def test_rejects_non_html_content():
    s = Session({"https://a.example/f": Resp(200, {"Content-Type": "application/zip"}, "x")})
    with pytest.raises(ValueError):
        fetch_page("https://a.example/f", resolver=PUBLIC, session=s)
