import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    llm_base_url: str = "https://api.groq.com/openai/v1"
    newsapi_key: str = ""
    google_factcheck_api_key: str = ""
    max_page_chars: int = 4000
    request_timeout: int = 20
    max_steps: int = 8                  # tool-calling rounds before the report is forced
    max_context_chars: int = 28000      # older page text is trimmed beyond this (saves tokens)
    llm_max_retries: int = 3
    timezone: str = "Asia/Kolkata"      # used for "this week" / "today" date windows
    cache_dir: str = "data/cache"
    cache_ttl_seconds: int = 3600       # 0 disables the cache
    docs_dir: str = "data/docs"


def _int(name: str, default: int, minimum: int = 0) -> int:
    raw = os.getenv(name, "").strip()
    try:
        return max(minimum, int(raw)) if raw else default
    except ValueError:
        return default


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        groq_api_key=os.getenv("GROQ_API_KEY", "").strip(),
        groq_model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b").strip(),
        llm_base_url=os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1").strip(),
        newsapi_key=os.getenv("NEWSAPI_KEY", "").strip(),
        google_factcheck_api_key=os.getenv("GOOGLE_FACTCHECK_API_KEY", "").strip(),
        max_page_chars=_int("MAX_PAGE_CHARS", 4000, 1000),
        request_timeout=_int("REQUEST_TIMEOUT", 20, 3),
        max_steps=_int("MAX_STEPS", 8, 2),
        max_context_chars=_int("MAX_CONTEXT_CHARS", 28000, 6000),
        llm_max_retries=_int("LLM_MAX_RETRIES", 3, 0),
        timezone=os.getenv("TIMEZONE", "Asia/Kolkata").strip(),
        cache_dir=os.getenv("CACHE_DIR", "data/cache").strip(),
        cache_ttl_seconds=_int("CACHE_TTL_SECONDS", 3600, 0),
        docs_dir=os.getenv("DOCS_DIR", "data/docs").strip(),
    )
