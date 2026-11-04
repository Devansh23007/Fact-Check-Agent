"""Search your own documents (txt, md, pdf) with BM25. No vector DB or embeddings needed."""
import math
import re
from collections import Counter
from pathlib import Path

_WORD = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "was", "were", "that", "this", "it", "with", "as", "by", "at", "be"}


def _tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOP]


def _read(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            return ""
        return "\n".join((page.extract_text() or "") for page in PdfReader(str(path)).pages)
    return path.read_text(encoding="utf-8", errors="ignore")


def _chunks(text: str, size: int = 120, overlap: int = 20) -> list[str]:
    words = text.split()
    step = max(1, size - overlap)
    return [" ".join(words[i:i + size]) for i in range(0, max(1, len(words)), step) if words[i:i + size]]


class DocsIndex:
    def __init__(self, docs_dir: str | Path, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.chunks: list[dict] = []
        root = Path(docs_dir)
        if root.is_dir():
            for path in sorted(root.rglob("*")):
                if path.is_file() and path.suffix.lower() in {".txt", ".md", ".pdf"}:
                    try:
                        text = _read(path)
                    except Exception:
                        continue
                    for n, chunk in enumerate(_chunks(text), 1):
                        self.chunks.append({"source": path.name, "url": f"doc://{path.name}#{n}", "text": chunk,
                                            "tokens": Counter(_tokens(chunk)), "length": len(_tokens(chunk))})
        self.avg_len = (sum(c["length"] for c in self.chunks) / len(self.chunks)) if self.chunks else 0.0
        self.doc_freq = Counter(t for c in self.chunks for t in c["tokens"])

    def __bool__(self) -> bool:
        return bool(self.chunks)

    def search(self, query: str, k: int = 4) -> list[dict]:
        q = _tokens(query)
        n = len(self.chunks)
        scored = []
        for c in self.chunks:
            score = 0.0
            for term in q:
                tf = c["tokens"].get(term, 0)
                if not tf:
                    continue
                idf = math.log(1 + (n - self.doc_freq[term] + 0.5) / (self.doc_freq[term] + 0.5))
                score += idf * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * c["length"] / (self.avg_len or 1)))
            if score > 0:
                scored.append((score, c))
        scored.sort(key=lambda row: row[0], reverse=True)
        return [{"source": c["source"], "url": c["url"], "text": c["text"], "score": round(s, 3)} for s, c in scored[:k]]
