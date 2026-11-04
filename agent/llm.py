"""Thin provider wrapper (OpenAI-compatible, so Groq / OpenAI / others work) with retries."""
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


class GroqLLM:
    def __init__(self, settings, client=None, sleep=time.sleep) -> None:
        self.model = settings.groq_model
        self.max_retries = settings.llm_max_retries
        self.sleep = sleep
        self.client = client or OpenAI(api_key=settings.groq_api_key, base_url=settings.llm_base_url,
                                       timeout=max(settings.request_timeout, 60), max_retries=0)

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
                last_error, wait = type(exc).__name__, self._wait_time(exc, attempt)
            except openai.BadRequestError as exc:
                # Open models occasionally emit a malformed tool call; a retry usually fixes it.
                retryable = "tool_use_failed" in str(exc) or "Failed to call a function" in str(exc)
                last_error, wait = "malformed tool call", 1.0
                if not retryable:
                    raise LLMError(f"The model API rejected the request: {str(exc)[:200]}") from exc
            except openai.AuthenticationError as exc:
                raise LLMError("The model API key was rejected. Check GROQ_API_KEY.") from exc
            except openai.APIStatusError as exc:
                raise LLMError(f"Model API error (HTTP {exc.status_code}).") from exc
            if attempt >= self.max_retries:
                raise LLMError(f"Model API still failing after {self.max_retries + 1} attempts ({last_error}).")
            self.sleep(wait)
        raise LLMError("Model API unavailable")  # pragma: no cover

    @staticmethod
    def _wait_time(exc: Exception, attempt: int) -> float:
        headers = getattr(getattr(exc, "response", None), "headers", None) or {}
        try:
            return min(float(headers.get("retry-after")), 30.0)
        except (TypeError, ValueError):
            return float(min(2 ** (attempt + 1), 20))
