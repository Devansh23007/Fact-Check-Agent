import os
from dataclasses import dataclass

from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    api_key: str
    model: str
    base_url: str


# name -> (key env var, model env var, default model, OpenAI-compatible base URL)
# Free-tier limits and model catalogues change often: confirm them in each provider's console.
PROVIDER_DEFAULTS = {
    "gemini": ("GEMINI_API_KEY", "GEMINI_MODEL", "gemini-2.5-flash", "https://generativelanguage.googleapis.com/v1beta/openai/"),
    "groq": ("GROQ_API_KEY", "GROQ_MODEL", "openai/gpt-oss-120b", "https://api.groq.com/openai/v1"),
    "mistral": ("MISTRAL_API_KEY", "MISTRAL_MODEL", "mistral-small-latest", "https://api.mistral.ai/v1"),
    "cerebras": ("CEREBRAS_API_KEY", "CEREBRAS_MODEL", "", "https://api.cerebras.ai/v1"),
    "openrouter": ("OPENROUTER_API_KEY", "OPENROUTER_MODEL", "", "https://openrouter.ai/api/v1"),
}
DEFAULT_ORDER = "gemini,groq,mistral,cerebras,openrouter"


@dataclass(frozen=True)
class Settings:
    providers: tuple[ProviderConfig, ...] = ()   # tried in order; the next one takes over on rate limits
    newsapi_key: str = ""
    google_factcheck_api_key: str = ""
    max_page_chars: int = 4000
    request_timeout: int = 20
    max_research_seconds: int = 90
    max_steps: int = 4                  # compact research loop for free-tier token budgets
    max_context_chars: int = 6000       # compact provider context; old exchanges are summarized
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


def load_providers() -> tuple[ProviderConfig, ...]:
    configured_order = os.getenv("LLM_PROVIDERS", "").strip() or os.getenv("LLM_PROVIDER_ORDER", DEFAULT_ORDER)
    order = [n.strip().lower() for n in configured_order.split(",") if n.strip()]
    providers = []
    for name in order:
        if name not in PROVIDER_DEFAULTS:
            continue
        key_var, model_var, default_model, base_url = PROVIDER_DEFAULTS[name]
        key = os.getenv(key_var, "").strip()
        model = os.getenv(model_var, "").strip() or default_model
        if key and model:   # providers without a key (or, for cerebras/openrouter, an explicit model) are skipped
            providers.append(ProviderConfig(name, key, model, os.getenv(f"{name.upper()}_BASE_URL", base_url).strip()))
    return tuple(providers)


def load_settings() -> Settings:
    env_path = Path(__file__).resolve().parent / ".env"
    load_dotenv(env_path if env_path.is_file() else None)
    return Settings(
        providers=load_providers(),
        newsapi_key=os.getenv("NEWSAPI_KEY", "").strip(),
        google_factcheck_api_key=os.getenv("GOOGLE_FACTCHECK_API_KEY", "").strip(),
        max_page_chars=_int("MAX_PAGE_CHARS", 4000, 1000),
        request_timeout=_int("REQUEST_TIMEOUT", 20, 3),
        max_research_seconds=_int("MAX_RESEARCH_SECONDS", 90, 30),
        max_steps=_int("MAX_STEPS", 4, 2),
        max_context_chars=_int("MAX_CONTEXT_CHARS", 6000, 4000),
        llm_max_retries=_int("LLM_MAX_RETRIES", 3, 0),
        timezone=os.getenv("TIMEZONE", "Asia/Kolkata").strip(),
        cache_dir=os.getenv("CACHE_DIR", "data/cache").strip(),
        cache_ttl_seconds=_int("CACHE_TTL_SECONDS", 3600, 0),
        docs_dir=os.getenv("DOCS_DIR", "data/docs").strip(),
    )
