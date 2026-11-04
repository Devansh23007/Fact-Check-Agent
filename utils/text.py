import html
import re

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def clean_text(value: str | None, limit: int | None = None) -> str:
    """Strip HTML tags/entities (Google News RSS summaries are HTML) and collapse whitespace."""
    text = _SPACE.sub(" ", html.unescape(_TAG.sub(" ", value or ""))).strip()
    return text[:limit] if limit else text
