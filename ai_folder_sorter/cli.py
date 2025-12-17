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
    p.add_argument("--local-path", required=True, help="Local folder path to organize (bounded depth).")
    p.add_argument("--max-chars", type=int, default=60000, help="Max chars per extracted preview (default: 60000).")
    p.add_argument("--min-chars", type=int, default=500, help="Minimum extracted text to proceed (default: 500).")
    p.add_argument(
        "--min-cluster-size",
        type=int,
        default=0,
        help="Minimum cluster size to justify a split (default: 0 = auto-dynamic based on file count).",
    )
    p.add_argument("--apply", action="store_true", help="Perform writes/moves (prompts first).")
    p.add_argument(
        "--show-summaries",
        action="store_true",
        help="Print a human-readable summary and include it in the JSON report.",
    )
    p.add_argument("--adk-timeout-seconds", type=int, default=120, help="Timeout for each LLM call (default: 120).")
    p.add_argument("--model-summary", default="gemini-2.0-flash-lite", help="Model for summariser.")
    p.add_argument("--model-planner", default="gemini-2.0-flash-lite", help="Model for global planner.")
    p.add_argument("--model-critic", default="gemini-2.0-flash-lite", help="Model for critic.")
    p.add_argument("--model-repair", default="gemini-2.0-flash-lite", help="Model for repair agent.")
    p.add_argument(
        "--critic-iterations",
        type=int,
        default=2,
        help="Max critic/repair iterations for global plan review (default: 2).",
    )
    p.add_argument("--logging", action="store_true", help="Emit structured log-style lines.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = _parse_args(argv)

    target = Path(args.local_path).expanduser().resolve()
    models = adk_agents.Models(
        summariser=args.model_summary,
        planner=args.model_planner,
        critic=args.model_critic,
        repair=args.model_repair,
    )

    try:
        report = build_local_plan(
            target=target,
            models=models,
            max_chars=args.max_chars,
            min_chars=args.min_chars,
            min_cluster_size=args.min_cluster_size,
            critic_iterations=args.critic_iterations,
            show_summaries=args.show_summaries,
            logging=args.logging,
            adk_timeout_seconds=args.adk_timeout_seconds,
        )
    except RuntimeError as e:
        print(f"Error: {e}")
        return 1

    if args.show_summaries and report.get("human_summary"):
        print(report["human_summary"])

    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))

    if not args.apply:
        return 0

    if not bool(report.get("accepted")):
        print("\nRefusing to apply: global plan was not accepted by critic.")
        return 2

    # Confirm once.
    ensure_count = sum(1 for a in report.get("actions", []) if a.get("kind") == "create_folder")
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
