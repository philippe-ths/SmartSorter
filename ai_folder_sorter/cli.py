from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from . import adk_agents
from .planner import apply_local_plan, build_local_plan


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="ai_folder_sorter")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--folder-id", help="Target Google Drive folder ID (top-level).")
    g.add_argument("--local-path", help="Local folder path to organize (no recursion).")
    p.add_argument(
        "--skip-files",
        type=int,
        default=0,
        help="Number of top-level files to skip after filtering ignored files (default: 0).",
    )
    p.add_argument(
        "--max-files",
        type=int,
        default=7,
        help="Max top-level files to process (default: 7; 0 means no limit).",
    )
    p.add_argument("--max-chars", type=int, default=60000, help="Max chars per extracted preview (default: 60000).")
    p.add_argument("--min-chars", type=int, default=500, help="Minimum extracted text to proceed (default: 500).")
    p.add_argument("--apply", action="store_true", help="Perform writes/moves (prompts first).")
    p.add_argument(
        "--show-summaries",
        action="store_true",
        help="Print a human-readable summary and include it in the JSON report.",
    )
    p.add_argument("--adk-timeout-seconds", type=int, default=120, help="Timeout for each LLM call (default: 120).")
    p.add_argument("--model-summary", default="gemini-2.0-flash-lite", help="Model for summariser.")
    p.add_argument("--model-folder", default="gemini-2.0-flash-lite", help="Model for folder matcher.")
    p.add_argument("--model-critic", default="gemini-2.0-flash-lite", help="Model for critic.")
    p.add_argument(
        "--critic-iterations",
        type=int,
        default=2,
        help="Max critic iterations per file (total; default: 2).",
    )
    p.add_argument("--logging", action="store_true", help="Emit structured log-style lines.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = _parse_args(argv)

    if args.folder_id:
        raise SystemExit("Drive folder mode is not implemented in this scratch rebuild. Use --local-path.")

    target = Path(args.local_path).expanduser().resolve()
    models = adk_agents.Models(summariser=args.model_summary, matcher=args.model_folder, critic=args.model_critic)

    report = build_local_plan(
        target=target,
        models=models,
        skip_files=args.skip_files,
        max_files=args.max_files,
        max_chars=args.max_chars,
        min_chars=args.min_chars,
        critic_iterations=args.critic_iterations,
        show_summaries=args.show_summaries,
        logging=args.logging,
        adk_timeout_seconds=args.adk_timeout_seconds,
    )

    if args.show_summaries and report.get("human_summary"):
        print(report["human_summary"])

    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))

    if not args.apply:
        return 0

    # Confirm once.
    ensure_count = sum(1 for a in report.get("actions", []) if a.get("kind") == "ensure_folder")
    move_count = sum(1 for a in report.get("actions", []) if a.get("kind") == "move_file")
    index_count = sum(1 for a in report.get("actions", []) if a.get("kind") == "update_index")
    skip_count = sum(1 for a in report.get("actions", []) if a.get("kind") == "skip_file")

    print(
        f"\nApply changes? folders={ensure_count} moves={move_count} index_updates={index_count} skipped={skip_count} (yes/no): ",
        end="",
        flush=True,
    )
    answer = (input() or "").strip().lower()
    if answer not in {"y", "yes"}:
        print("Aborted.")
        return 1

    apply_local_plan(target=target, report=report, logging=args.logging)
    return 0
