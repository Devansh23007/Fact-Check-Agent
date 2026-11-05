"""OpenAI-compatible LLM clients with per-run provider failover."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import openai
from openai import OpenAI


class LLMError(RuntimeError):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str


@dataclass
class LLMResponse:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)

    def to_message(self) -> dict:
        message: dict = {"role": "assistant", "content": self.content or None}
        if self.tool_calls:
            message["tool_calls"] = [
                {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                for c in self.tool_calls
            ]
        return message


class ProviderRouter:
    """Try configured providers in order; rate limited or unavailable providers are skipped."""

    def __init__(self, settings, clients: dict[str, object] | None = None, sleep=time.sleep, log=None) -> None:
        self.settings = settings
        self.sleep = sleep
        self.log = log or (lambda message: print(message, flush=True))
        self.clients = clients or {}
        self.providers: list[dict] = []
        self.disabled: dict[str, str] = {}
        self.cooldowns: dict[str, float] = {}
        self.calls: dict[str, int] = {}
        self.model = ""

        for cfg in settings.providers:
            name, model = cfg.name, cfg.model
            client = self.clients.get(name) or OpenAI(
                api_key=cfg.api_key, base_url=cfg.base_url,
                timeout=settings.request_timeout, max_retries=0
            )
            self.providers.append({"name": name, "model": model, "client": client})
        if not self.providers:
            raise LLMError("No AI provider is configured. Add at least one supported provider key to .env.")

    @property
    def active_provider_names(self) -> list[str]:
        return [f"{p['name']} ({p['model']})" for p in self.providers if p["name"] not in self.disabled]

    def chat(self, messages: list[dict], tools: list[dict], tool_choice="auto", max_tokens: int = 2000) -> LLMResponse:
        attempted: set[str] = set()
        cooldown_waited = False
        while True:
            now = time.monotonic()
            candidates = [p for p in self.providers if p["name"] not in self.disabled
                          and p["name"] not in attempted and self.cooldowns.get(p["name"], 0) <= now]
            if not candidates:
                remaining = [self.cooldowns[p["name"]] - now for p in self.providers
                             if p["name"] not in self.disabled and self.cooldowns.get(p["name"], 0) > now]
                if remaining:
                    wait = min(remaining)
                    if wait <= 15 and not cooldown_waited:
                        self.log(f"  AI provider in cooldown; waiting {int(wait) + 1}s for rate limit to reset...")
                        self.sleep(wait + 0.5)
                        cooldown_waited = True
                        attempted.clear()
                        continue
                    raise LLMError(f"All configured AI providers are rate limited; retry in about {int(wait)} seconds.")
                break

            provider = candidates[0]
            name = provider["name"]
            attempted.add(name)
            try:
                response = self._request(provider, messages, tools, tool_choice, max_tokens)
                self.calls[name] = self.calls.get(name, 0) + 1
                self.model = f"{name}/{provider['model']}"
                return response
            except openai.RateLimitError as exc:
                wait = self._retry_after(exc)
                self.cooldowns[name] = time.monotonic() + wait
                self.log(f"  {name} rate limited; trying next provider (cooldown ~{int(wait)}s).")
            except (openai.APIConnectionError, openai.APITimeoutError, openai.InternalServerError) as exc:
                self.log(f"  {name} unavailable ({type(exc).__name__}); trying next provider.")
            except openai.AuthenticationError:
                self.disabled[name] = "key rejected"
                self.log(f"  {name} disabled for this run: API key rejected.")
            except openai.NotFoundError:
                self.disabled[name] = "model unavailable"
                self.log(f"  {name} disabled for this run: model not found or unavailable.")
            except openai.BadRequestError as exc:
                error_text = f"{getattr(exc, 'message', '')} {getattr(exc, 'body', '')} {exc}".lower()
                # A provider may reject forced submit_report. Retry as any required function call;
                # the final-step prompt tells the model to choose submit_report.
                if isinstance(tool_choice, dict):
                    try:
                        response = self._request(provider, messages, tools, "auto", max_tokens)
                        self.calls[name] = self.calls.get(name, 0) + 1
                        self.model = f"{name}/{provider['model']}"
                        return response
                    except openai.BadRequestError:
                        pass
                    except openai.APIError:
                        pass
                # One retry for provider-side malformed tool-call serialization.
                malformed_tool = any(term in error_text for term in (
                    "tool_use_failed", "malformed", "failed_generation", "invalid tool call",
                    "tool call arguments", "arguments are not valid json",
                    "tool call validation failed", "does not match request.tool_choice",
                    "which was not in request.tools", "tool choice is required",
                ))
                if malformed_tool:
                    try:
                        response = self._request(provider, messages, tools, "auto", max_tokens)
                        self.calls[name] = self.calls.get(name, 0) + 1
                        self.model = f"{name}/{provider['model']}"
                        return response
                    except openai.BadRequestError:
                        pass
                    except openai.APIError:
                        pass
                self.disabled[name] = "request/tool compatibility error"
                detail = str(getattr(exc, "message", "") or "").replace("\n", " ").strip()[:180]
                self.log(f"  {name} rejected this request (HTTP 400); skipping it for this run." + (f" Detail: {detail}" if detail else ""))
            except openai.APIStatusError as exc:
                if exc.status_code == 404:
                    self.disabled[name] = "model unavailable"
                    self.log(f"  {name} disabled for this run: model not found or unavailable.")
                else:
                    self.log(f"  {name} returned HTTP {exc.status_code}; trying next provider.")

        statuses = ", ".join(f"{p['name']}: {self.disabled.get(p['name'], 'unavailable or rate limited')}" for p in self.providers)
        raise LLMError(f"All configured AI providers failed ({statuses}).")

    @staticmethod
    def _request(provider, messages, tools, tool_choice, max_tokens) -> LLMResponse:
        response = provider["client"].chat.completions.create(
            model=provider["model"], messages=messages, tools=tools,
            tool_choice=tool_choice, max_tokens=max_tokens,
        )
        message = response.choices[0].message
        calls = [ToolCall(id=c.id, name=c.function.name, arguments=c.function.arguments or "{}")
                 for c in (message.tool_calls or [])]
        return LLMResponse(content=message.content or "", tool_calls=calls)

    @staticmethod
    def _retry_after(exc: Exception) -> float:
        headers = getattr(getattr(exc, "response", None), "headers", None) or {}
        try:
            return max(0.0, min(float(headers.get("retry-after")), 86400.0))
        except (TypeError, ValueError):
            reset = str(headers.get("x-ratelimit-reset-tokens", "")).lower().rstrip("s ")
            try:
                return max(0.0, min(float(reset), 86400.0))
            except (TypeError, ValueError):
                return 2.0


class GroqLLM:
    """Backward-compatible Groq-only client retained for existing callers."""

    def __init__(self, settings, client=None, sleep=time.sleep) -> None:
        self.model = settings.groq_model
        self.max_retries = settings.llm_max_retries
        self.sleep = sleep
        self.client = client or OpenAI(api_key=settings.groq_api_key, base_url=settings.llm_base_url,
                                       timeout=settings.request_timeout, max_retries=0)

    def chat(self, messages: list[dict], tools: list[dict], tool_choice="auto", max_tokens: int = 2000) -> LLMResponse:
        last_error = "unknown error"
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model, messages=messages, tools=tools, tool_choice=tool_choice, max_tokens=max_tokens)
                message = response.choices[0].message
                calls = [ToolCall(id=c.id, name=c.function.name, arguments=c.function.arguments or "{}")
                         for c in (message.tool_calls or [])]
                return LLMResponse(content=message.content or "", tool_calls=calls)
            except (openai.RateLimitError, openai.APIConnectionError, openai.APITimeoutError, openai.InternalServerError) as exc:
                last_error, wait = type(exc).__name__, ProviderRouter._retry_after(exc)
            except openai.AuthenticationError as exc:
                raise LLMError("The model API key was rejected. Check GROQ_API_KEY.") from exc
            except openai.APIStatusError as exc:
                raise LLMError(f"Model API error (HTTP {exc.status_code}).") from exc
            if attempt >= self.max_retries:
                raise LLMError(f"Model API still failing after {self.max_retries + 1} attempts ({last_error}).")
            self.sleep(wait)
        raise LLMError("Model API unavailable")  # pragma: no cover
