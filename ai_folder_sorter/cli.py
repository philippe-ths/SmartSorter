from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
from dataclasses import asdict

from .planner import build_plan, execute_plan


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ai_folder_sorter")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--folder-id", help="Target Google Drive folder ID (top-level).")
    group.add_argument("--local-path", help="Local folder path to organize (no recursion).")
    p.add_argument("--max-chars", type=int, default=60_000, help="Max chars per extracted preview (default: 60000).")
    p.add_argument("--apply", action="store_true", help="Perform writes/moves (prompts first).")
    p.add_argument(
        "--show-summaries",
        action="store_true",
        help="Print a human-readable summary (folders + per-file summary/decision) and include it in the JSON report.",
    )
    p.add_argument(
        "--adk-timeout-seconds",
        type=int,
        default=120,
        help="Timeout for each ADK call (default: 120).",
    )
    p.add_argument(
        "--supports-all-drives",
        action="store_true",
        help="Enable supportsAllDrives=True for Shared Drives.",
    )
    p.add_argument(
        "--model-summary",
        default="gemini-2.5-flash",
        help="ADK model for summarizer (default: gemini-2.5-flash).",
    )
    p.add_argument(
        "--model-folder",
        default="gemini-2.5-flash",
        help="ADK model for folder matcher (default: gemini-2.5-flash).",
    )
    p.add_argument(
        "--model-critic",
        default="gemini-2.5-flash",
        help="ADK model for critic (default: gemini-2.5-flash).",
    )
    p.add_argument(
        "--critic-iterations",
        type=int,
        default=2,
        help="Max critic refinement iterations after initial decisions (default: 2).",
    )
    return p


def _existing_folder_names(plan, *, supports_all_drives: bool) -> list[str]:
    if plan.mode == "local":
        if not plan.local_path:
            return []
        base = Path(plan.local_path)
        if not base.exists():
            return []
        return sorted([p.name for p in base.iterdir() if p.is_dir()], key=lambda x: x.lower())

    if not plan.folder_id:
        return []
    from .drive import list_top_level_children

    items = list_top_level_children(plan.folder_id, supports_all_drives=supports_all_drives)
    return sorted([i.name for i in items if i.is_folder], key=lambda x: x.lower())


def _print_show_summaries(plan, *, supports_all_drives: bool) -> None:
    existing_folders = _existing_folder_names(plan, supports_all_drives=supports_all_drives)
    existing_set = set(existing_folders)

    folder_to_files: dict[str, list[str]] = defaultdict(list)
    for a in plan.actions:
        if a.kind != "move_file":
            continue
        if not a.folder_name or not a.file_name:
            continue
        folder_to_files[a.folder_name].append(a.file_name)

    for files in folder_to_files.values():
        files.sort(key=lambda x: x.lower())

    print("Folders (existing) and what they should contain:")
    if not existing_folders:
        print("- (none found)")
    else:
        for name in existing_folders:
            planned = folder_to_files.get(name, [])
            if planned:
                print(f"- {name}: {', '.join(planned)}")
            else:
                print(f"- {name}: (no files planned)")

    new_folders = sorted([n for n in folder_to_files.keys() if n not in existing_set], key=lambda x: x.lower())
    if new_folders:
        print("\nFolders (new) and what they should contain:")
        for name in new_folders:
            planned = folder_to_files.get(name, [])
            print(f"- {name}: {', '.join(planned)}")

    file_reports = [r for r in plan.report if isinstance(r, dict) and r.get("filename")]
    if not file_reports:
        return

    print("\nFiles:")
    for r in file_reports:
        filename = r.get("filename") or ""
        summary_obj = r.get("summary") if isinstance(r.get("summary"), dict) else {}
        summary_text = (summary_obj.get("summary") or "").strip()

        decision_final = r.get("decision_final") if isinstance(r.get("decision_final"), dict) else None
        decision_initial = r.get("decision_initial") if isinstance(r.get("decision_initial"), dict) else None
        decision = decision_final or decision_initial or {}
        tf = decision.get("target_folder") if isinstance(decision.get("target_folder"), dict) else {}
        folder_name = (tf.get("name") or "").strip()
        exists = bool(tf.get("exists"))

        changed = bool(r.get("critic_changed"))
        if changed:
            change = r.get("critic_change") if isinstance(r.get("critic_change"), dict) else {}
            tf_change = change.get("target_folder") if isinstance(change.get("target_folder"), dict) else {}
            from_name = (tf_change.get("from") or "").strip()
            to_name = (tf_change.get("to") or "").strip()
            if from_name or to_name:
                decision_line = f"{folder_name} ({'existing' if exists else 'new'}) [critic: {from_name} -> {to_name or folder_name}]"
            else:
                decision_line = f"{folder_name} ({'existing' if exists else 'new'}) [critic revised]"
        else:
            decision_line = f"{folder_name} ({'existing' if exists else 'new'})"

        print(f"- {filename}")
        print(f"  Summary: {summary_text}")
        print(f"  Decision: {decision_line}")


def main(argv: list[str] | None = None) -> int:
    # Convenience: allow env vars (GOOGLE_API_KEY, GOOGLE_OAUTH_CLIENT_FILE, etc.)
    # to be stored in a local `.env` without requiring users to `source` it.
    try:
        from dotenv import load_dotenv  # type: ignore

        repo_env = Path(__file__).resolve().parents[1] / ".env"
        if repo_env.exists():
            load_dotenv(dotenv_path=repo_env, override=False)
        load_dotenv(override=False)
    except Exception:
        pass

    args = _parser().parse_args(argv)

    plan = build_plan(
        folder_id=args.folder_id,
        local_path=args.local_path,
        max_chars=args.max_chars,
        supports_all_drives=args.supports_all_drives,
        model_summary=args.model_summary,
        model_folder=args.model_folder,
        model_critic=args.model_critic,
        critic_iterations=args.critic_iterations,
        adk_timeout_seconds=args.adk_timeout_seconds,
        emit_report=args.show_summaries,
    )

    if args.show_summaries:
        _print_show_summaries(plan, supports_all_drives=args.supports_all_drives)
        print("")

    if not args.apply:
        out = {"report": plan.report, "actions": [asdict(a) for a in plan.actions]}
        print(json.dumps(out, indent=2, sort_keys=True))
        return 0

    execute_plan(plan, supports_all_drives=args.supports_all_drives)
    return 0
