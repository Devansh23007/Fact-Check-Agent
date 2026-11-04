from tools.docs_search import DocsIndex
from utils.cache import DiskCache
from utils.text import clean_text
from agent.loop import TRIM_MARK, trim_context
import json


def test_docs_search_ranks_relevant_chunk(tmp_path):
    (tmp_path / "budget.txt").write_text("The annual budget allocated funds to rural roads and bridges in the northern districts.")
    (tmp_path / "other.md").write_text("Cricket match report: the home side won by six wickets after a strong chase.")
    idx = DocsIndex(tmp_path)
    hits = idx.search("rural roads budget")
    assert hits and hits[0]["source"] == "budget.txt" and hits[0]["url"].startswith("doc://budget.txt#")
    assert idx.search("zzzz nothing") == []


def test_empty_docs_dir_is_falsy(tmp_path):
    assert not DocsIndex(tmp_path)


def test_clean_text_strips_html():
    assert clean_text("<a href='x'>Hello&nbsp;&amp; welcome</a>  <b>all</b>") == "Hello & welcome all"


def test_cache_roundtrip_and_ttl(tmp_path):
    calls = []
    cache = DiskCache(tmp_path, ttl_seconds=60)
    f = lambda: calls.append(1) or {"v": 1}
    assert cache.get_or_set("ns", {"q": 1}, f) == {"v": 1}
    assert cache.get_or_set("ns", {"q": 1}, f) == {"v": 1}
    assert len(calls) == 1
    off = DiskCache(tmp_path, ttl_seconds=0)
    off.get_or_set("ns", {"q": 1}, f)
    assert len(calls) == 2


def test_trim_context_only_shrinks_old_bulky_tool_output():
    big = json.dumps({"url": "https://a.example/x", "title": "T", "text": "word " * 2000})
    search = json.dumps({"results": [{"url": "https://a.example/x"}] * 5})
    msgs = [{"role": "system", "content": "s"},
            {"role": "tool", "tool_call_id": "1", "content": search},
            {"role": "tool", "tool_call_id": "2", "content": big},
            {"role": "tool", "tool_call_id": "3", "content": big}]
    trim_context(msgs, {"2", "3"}, max_chars=12000)
    assert msgs[1]["content"] == search                       # search results untouched
    assert msgs[2]["content"].endswith(TRIM_MARK)             # oldest bulky output trimmed
    assert json.loads(msgs[2]["content"][:-len(TRIM_MARK)])["url"] == "https://a.example/x"
