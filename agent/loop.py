"""The agent loop: the model chooses tools, we run them, and it ends by calling submit_report."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from agent.llm import GroqLLM, LLMError
from agent.prompts import FORCE_SUBMIT_MESSAGE, NUDGE_MESSAGE, SYSTEM_PROMPT
from agent.schemas import FactCheckReport, ReportDraft, ResearchStep
from agent.sources import SourceRegistry
from agent.verify import fallback_report, finalize
from tools.docs_search import DocsIndex
from tools.registry import ToolBox
from utils.cache import DiskCache

TRIM_MARK = "…[trimmed to save tokens]"
FORCE_SUBMIT = {"type": "function", "function": {"name": "submit_report"}}


def trim_context(messages: list[dict], bulky_ids: set[str], max_chars: int, keep: int = 300) -> None:
    """Shrink the oldest large tool outputs (page text, doc passages) once the transcript is too long.

    Search results are never trimmed, so the model can still see which URLs it may cite.
    """
    def total() -> int:
        return sum(len(m.get("content") or "") for m in messages)

    for message in messages:
        if total() <= max_chars:
            return
        content = message.get("content") or ""
        if message.get("role") != "tool" or message.get("tool_call_id") not in bulky_ids or content.endswith(TRIM_MARK):
            continue
        if len(content) <= keep + 100:
            continue
        try:
            data = json.loads(content)
            text = data.get("text") or json.dumps(data.get("results", ""), ensure_ascii=False)
            slim = {k: data[k] for k in ("url", "title") if k in data}
            slim["text"] = text[:keep]
            message["content"] = json.dumps(slim, ensure_ascii=False) + TRIM_MARK
        except (json.JSONDecodeError, AttributeError):
            message["content"] = content[:keep] + TRIM_MARK


def build_toolbox(settings, registry: SourceRegistry, log) -> ToolBox:
    cache = DiskCache(settings.cache_dir, settings.cache_ttl_seconds) if settings.cache_ttl_seconds > 0 else None
    docs = DocsIndex(settings.docs_dir)
    if docs:
        log(f"Indexed {len(docs.chunks)} passage(s) from local documents in {settings.docs_dir}")
    return ToolBox(settings, registry, cache=cache, docs=docs or None, log=log)


def run_agent(topic: str, settings, *, llm=None, toolbox: ToolBox | None = None, log=None) -> FactCheckReport:
    log = log or (lambda message: print(message, flush=True))
    if llm is None:
        if not settings.groq_api_key:
            raise RuntimeError("Set GROQ_API_KEY in your .env file before running the agent.")
        llm = GroqLLM(settings)
    toolbox = toolbox or build_toolbox(settings, SourceRegistry(), log)
    registry = toolbox.registry

    today = datetime.now(ZoneInfo(settings.timezone)).date().isoformat()
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT.format(today=today, tz=settings.timezone, max_steps=settings.max_steps)},
        {"role": "user", "content": f"Topic or claim to fact-check: {topic}"},
    ]
    research_log: list[ResearchStep] = []
    tools = toolbox.schemas()
    nudged, repairs = False, 0
    log(f"Fact-checking: {topic}")

    try:
        for step in range(1, settings.max_steps + 1):
            final_step = step == settings.max_steps
            if final_step:
                messages.append({"role": "user", "content": FORCE_SUBMIT_MESSAGE})
            trim_context(messages, toolbox.bulky_ids, settings.max_context_chars)
            response = llm.chat(messages, tools, tool_choice=FORCE_SUBMIT if final_step else "auto")
            messages.append(response.to_message())

            if not response.tool_calls:
                if nudged or final_step:
                    break
                nudged = True
                messages.append({"role": "user", "content": NUDGE_MESSAGE})
                continue

            report: FactCheckReport | None = None
            for call in response.tool_calls:
                if report is not None:
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps({"ignored": "report already submitted"})})
                    continue
                if call.name == "submit_report":
                    try:
                        draft = ReportDraft.model_validate_json(call.arguments)
                    except ValidationError as exc:
                        repairs += 1
                        problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:4])
                        messages.append({"role": "tool", "tool_call_id": call.id,
                                         "content": json.dumps({"error": f"Invalid report: {problems}. Fix it and call submit_report again."})})
                        log(f"  step {step}: submit_report was invalid ({problems[:100]})")
                        if repairs > 2:
                            raise LLMError("The model could not produce a valid report.")
                        continue
                    report = finalize(topic, draft, registry, research_log, llm.model if hasattr(llm, "model") else settings.groq_model)
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps({"ok": True})})
                    continue

                result, summary = toolbox.call(call.name, call.arguments, call.id)
                try:
                    shown_args = json.loads(call.arguments or "{}")
                except json.JSONDecodeError:
                    shown_args = {"raw": call.arguments[:100]}
                research_log.append(ResearchStep(step=step, tool=call.name, arguments=shown_args if isinstance(shown_args, dict) else {}, summary=summary))
                log(f"  step {step}: {call.name}({', '.join(f'{k}={str(v)[:60]}' for k, v in (shown_args or {}).items())}) -> {summary}")
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result})

            if report is not None:
                log(f"Finished: {len(report.verdicts)} claim(s) assessed from {len(registry)} source(s).")
                return report
    except LLMError as exc:
        log(f"  Model unavailable: {exc}")
        return fallback_report(topic, registry, research_log, f"AI analysis could not be completed: {exc}", settings.groq_model)

    return fallback_report(topic, registry, research_log,
                           "The agent ended without submitting a report; the sources it retrieved are listed unassessed.", settings.groq_model)
