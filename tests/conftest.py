import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.llm import LLMResponse, ToolCall  # noqa: E402
from config import Settings  # noqa: E402


def make_settings(**kw) -> Settings:
    base = dict(groq_api_key="test", newsapi_key="n", google_factcheck_api_key="g", cache_ttl_seconds=0, max_steps=6)
    base.update(kw)
    return Settings(**base)


def call(name: str, args: dict, cid: str = "c1") -> ToolCall:
    return ToolCall(id=cid, name=name, arguments=json.dumps(args))


class ScriptedLLM:
    """Plays back a fixed list of responses and records what it was asked."""
    model = "fake-model"

    def __init__(self, responses: list[LLMResponse]):
        self.responses, self.seen_tool_choices, self.seen_messages = list(responses), [], []

    def chat(self, messages, tools, tool_choice="auto", max_tokens=2000):
        self.seen_tool_choices.append(tool_choice)
        self.seen_messages.append(json.loads(json.dumps(messages)))
        return self.responses.pop(0)
