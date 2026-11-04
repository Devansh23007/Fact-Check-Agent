import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable


class DiskCache:
    """Tiny JSON file cache so repeated runs don't burn NewsAPI / Fact Check / page-fetch quota."""

    def __init__(self, directory: str | Path, ttl_seconds: int) -> None:
        self.directory = Path(directory)
        self.ttl = ttl_seconds

    def _path(self, namespace: str, params: dict) -> Path:
        digest = hashlib.sha256(json.dumps([namespace, params], sort_keys=True, default=str).encode()).hexdigest()
        return self.directory / f"{namespace}-{digest[:24]}.json"

    def get_or_set(self, namespace: str, params: dict, producer: Callable[[], Any]) -> Any:
        if self.ttl <= 0:
            return producer()
        path = self._path(namespace, params)
        try:
            if path.exists() and time.time() - path.stat().st_mtime < self.ttl:
                return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
        value = producer()
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        except (OSError, TypeError):
            pass
        return value
