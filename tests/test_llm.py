import httpx
import openai
import pytest

from agent.llm import GroqLLM, LLMError
from tests.conftest import make_settings


def _rate_limit(headers=None):
    req = httpx.Request("POST", "https://x.example")
    return openai.RateLimitError("slow down", response=httpx.Response(429, request=req, headers=headers or {}), body=None)


class _Msg:
    content, tool_calls = "hello", None


class _Resp:
    choices = [type("C", (), {"message": _Msg()})()]


class _Client:
    def __init__(self, failures):
        self.failures, self.calls = failures, 0
        self.chat = type("Chat", (), {"completions": self})()

    def create(self, **kw):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return _Resp()


def test_retries_rate_limit_then_succeeds_using_retry_after():
    sleeps = []
    client = _Client([_rate_limit({"retry-after": "3"}), _rate_limit()])
    llm = GroqLLM(make_settings(llm_max_retries=3), client=client, sleep=sleeps.append)
    assert llm.chat([], []).content == "hello"
    assert client.calls == 3 and sleeps[0] == 3.0


def test_gives_up_after_max_retries():
    llm = GroqLLM(make_settings(llm_max_retries=1), client=_Client([_rate_limit(), _rate_limit(), _rate_limit()]), sleep=lambda s: None)
    with pytest.raises(LLMError):
        llm.chat([], [])
