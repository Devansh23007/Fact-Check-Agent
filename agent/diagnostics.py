"""`python main.py --check`: test every configured LLM provider with a tiny request."""
import os

import openai
from openai import OpenAI

from config import PROVIDER_DEFAULTS


def check_providers(settings, log=print, client_factory=None) -> bool:
    log("API keys found in your environment / .env:")
    for name, (key_var, _model_var, _default, _url) in PROVIDER_DEFAULTS.items():
        log(f"  {key_var}: {'set' if os.getenv(key_var, '').strip() else 'MISSING'}")
    if not settings.providers:
        log("\nNo usable provider. Make sure .env is in the folder you run from and the variable names match exactly.")
        return False

    log("\nTesting providers in priority order:")
    any_ok = False
    for cfg in settings.providers:
        client = (client_factory or OpenAI)(api_key=cfg.api_key, base_url=cfg.base_url, timeout=30, max_retries=0)
        label = f"{cfg.name}/{cfg.model}"
        try:
            client.chat.completions.create(model=cfg.model, max_tokens=20,
                                           messages=[{"role": "user", "content": "Reply with the single word: ok"}])
            log(f"  OK            {label}")
            any_ok = True
        except openai.RateLimitError:
            log(f"  RATE LIMITED  {label} (key works; wait a minute)")
            any_ok = True
        except openai.AuthenticationError:
            log(f"  BAD KEY       {label} (key rejected; recreate it)")
        except openai.NotFoundError:
            log(f"  NO SUCH MODEL {label} (change the *_MODEL value in .env)")
        except Exception as exc:
            log(f"  FAILED        {label}: {type(exc).__name__}: {str(exc)[:160]}")
    return any_ok