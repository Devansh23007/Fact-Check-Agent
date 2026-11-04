import argparse
import dataclasses
import json
from datetime import datetime, timezone
from pathlib import Path

from agent.loop import run_agent
from config import load_settings
from utils.render import to_markdown


def main() -> None:
    parser = argparse.ArgumentParser(description="Research a news claim and produce an evidence-linked fact-check.")
    parser.add_argument("topic", help="A claim or news topic to investigate")
    parser.add_argument("--max-steps", type=int, help="Maximum tool-calling rounds (default from MAX_STEPS)")
    parser.add_argument("--no-cache", action="store_true", help="Ignore and don't write the local result cache")
    parser.add_argument("--quiet", action="store_true", help="Hide step-by-step progress")
    args = parser.parse_args()

    settings = load_settings()
    overrides = {}
    if args.max_steps:
        overrides["max_steps"] = max(2, args.max_steps)
    if args.no_cache:
        overrides["cache_ttl_seconds"] = 0
    settings = dataclasses.replace(settings, **overrides)

    try:
        report = run_agent(args.topic, settings, log=(lambda m: None) if args.quiet else None)
    except RuntimeError as exc:
        parser.exit(1, f"\nError: {exc}\n")

    reports_dir = Path("data/reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (reports_dir / f"{stamp}.json").write_text(json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False), encoding="utf-8")
    markdown = to_markdown(report)
    (reports_dir / f"{stamp}.md").write_text(markdown, encoding="utf-8")
    print("\n" + markdown)
    print(f"Saved: {reports_dir / (stamp + '.json')} and .md")


if __name__ == "__main__":
    main()
