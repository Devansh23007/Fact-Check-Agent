import json

from agent.llm import LLMResponse
from agent.loop import run_agent
from agent.sources import SourceRegistry
from tools.registry import ToolBox
from tests.conftest import ScriptedLLM, call, make_settings

ARTICLE = "The Union Cabinet on Tuesday approved the new national semiconductor policy with a large outlay."


def _toolbox(settings, **kw):
    news = lambda q, **k: [
        {"title": "Cabinet approves chip policy", "url": "https://pib.gov.in/a", "source": "PIB",
         "published_at": "2099-01-02T10:00:00Z", "description": "Cabinet approved policy"},
        {"title": "Old story", "url": "https://old.example/x", "source": "Old", "published_at": "2001-01-01T00:00:00Z", "description": "old"},
    ]
    fetch = lambda url, **k: {"url": url, "title": "", "text": ARTICLE}
    return ToolBox(settings, SourceRegistry(), news_fn=news, fetch_fn=fetch,
                   factcheck_fn=lambda q, **k: [], log=lambda m: None, **kw)


REPORT = {"summary": "Policy approved.", "verdicts": [{
    "claim": "Cabinet approved a semiconductor policy", "verdict": "supported", "confidence": "high",
    "evidence": [{"url": "https://pib.gov.in/a", "stance": "supports", "excerpt": "approved the new national semiconductor policy"}]}]}


def test_full_loop_search_fetch_submit():
    s = make_settings()
    llm = ScriptedLLM([
        LLMResponse(tool_calls=[call("search_news", {"query": "semiconductor policy", "published_after": "2090-01-01"}, "a")]),
        LLMResponse(tool_calls=[call("fetch_page", {"url": "https://pib.gov.in/a"}, "b")]),
        LLMResponse(tool_calls=[call("submit_report", REPORT, "c")]),
    ])
    report = run_agent("Did Cabinet approve a chip policy?", s, llm=llm, toolbox=_toolbox(s), log=lambda m: None)
    v = report.verdicts[0]
    assert v.verdict == "supported" and v.evidence[0].excerpt_verified and v.evidence[0].source_tier == "official"
    assert [st.tool for st in report.research_log] == ["search_news", "fetch_page"]
    assert report.sources_considered[0].read_full_text
    # the 2001 article must have been filtered by the date window
    assert all("old.example" not in x.url for x in report.sources_considered)


def test_fetch_of_url_never_returned_by_search_is_rejected():
    s = make_settings()
    tb = _toolbox(s)
    out, _ = tb.call("fetch_page", json.dumps({"url": "https://evil.example/x"}))
    assert "not returned by a search tool" in json.loads(out)["error"]


def test_invalid_report_is_repaired():
    s = make_settings()
    llm = ScriptedLLM([
        LLMResponse(tool_calls=[call("search_news", {"query": "chip policy"}, "a")]),
        LLMResponse(tool_calls=[call("submit_report", {"summary": "x", "verdicts": []}, "b")]),
        LLMResponse(tool_calls=[call("submit_report", REPORT, "c")]),
    ])
    report = run_agent("t", s, llm=llm, toolbox=_toolbox(s), log=lambda m: None)
    assert report.verdicts[0].verdict == "supported"
    repair_msg = [m for m in llm.seen_messages[2] if m["role"] == "tool" and "Invalid report" in m["content"]]
    assert repair_msg


def test_plain_text_answer_is_nudged_once_then_falls_back():
    s = make_settings()
    llm = ScriptedLLM([LLMResponse(content="I think it's true."), LLMResponse(content="Really, it's true.")])
    report = run_agent("t", s, llm=llm, toolbox=_toolbox(s), log=lambda m: None)
    assert report.verdicts[0].verdict == "unverified" and report.warnings


def test_last_step_forces_submit_report():
    s = make_settings(max_steps=2)
    llm = ScriptedLLM([
        LLMResponse(tool_calls=[call("search_news", {"query": "chip policy"}, "a")]),
        LLMResponse(tool_calls=[call("submit_report", REPORT, "b")]),
    ])
    run_agent("t", s, llm=llm, toolbox=_toolbox(s), log=lambda m: None)
    assert llm.seen_tool_choices[0] == "auto"
    assert llm.seen_tool_choices[1]["function"]["name"] == "submit_report"


def test_model_outage_returns_transparent_fallback_with_sources_so_far():
    from agent.llm import LLMError

    class Dying(ScriptedLLM):
        def chat(self, *a, **k):
            if self.responses:
                return self.responses.pop(0)
            raise LLMError("rate limited")

    s = make_settings()
    llm = Dying([LLMResponse(tool_calls=[call("search_news", {"query": "chip policy"}, "a")])])
    report = run_agent("t", s, llm=llm, toolbox=_toolbox(s), log=lambda m: None)
    v = report.verdicts[0]
    assert v.verdict == "unverified" and v.evidence and "rate limited" in report.summary


def test_tool_errors_are_returned_to_model_not_raised():
    s = make_settings()
    tb = ToolBox(s, SourceRegistry(), news_fn=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")), log=lambda m: None)
    out, summary = tb.call("search_news", json.dumps({"query": "x"}))
    assert "error" in json.loads(out) and summary.startswith("failed")
    out, _ = tb.call("search_news", "{not json")
    assert "Invalid arguments" in json.loads(out)["error"]
