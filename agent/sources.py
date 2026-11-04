from dataclasses import dataclass

from agent.guardrails import normalize_url
from agent.reliability import classify


@dataclass
class Source:
    url: str
    title: str = ""
    publisher: str = ""
    kind: str = "news_article"   # news_article | published_fact_check | document
    published_at: str = ""
    snippet: str = ""
    article_text: str = ""
    rating: str = ""
    claim_reviewed: str = ""

    @property
    def tier(self) -> str:
        return classify(self.url, self.kind)

    @property
    def has_full_text(self) -> bool:
        return bool(self.article_text)

    def searchable_text(self) -> str:
        return " ".join(p for p in (self.title, self.snippet, self.claim_reviewed, self.rating, self.article_text) if p)


class SourceRegistry:
    """Every URL any tool has returned. The model may only cite or fetch URLs found here."""

    def __init__(self) -> None:
        self._sources: dict[str, Source] = {}
        self._aliases: dict[str, str] = {}

    def add(self, url: str, **fields) -> Source | None:
        if not url:
            return None
        key = self._aliases.get(normalize_url(url), normalize_url(url))
        source = self._sources.get(key)
        if source is None:
            source = Source(url=url)
            self._sources[key] = source
        for name, value in fields.items():
            if value:  # never overwrite known data with blanks
                setattr(source, name, value)
        return source

    def alias(self, original: str, final: str) -> None:
        """Record that `original` redirected to `final` so either URL can be cited."""
        orig, fin = normalize_url(original), normalize_url(final)
        if orig != fin and orig in self._sources:
            self._aliases[fin] = orig

    def get(self, url: str) -> Source | None:
        key = normalize_url(url)
        return self._sources.get(self._aliases.get(key, key))

    def all(self) -> list[Source]:
        return list(self._sources.values())

    def __len__(self) -> int:
        return len(self._sources)
