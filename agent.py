from __future__ import annotations

from typing import Any, Dict

from ai_folder_sorter.planner import build_plan

try:
    from google.adk.agents import LlmAgent
except Exception:  # pragma: no cover
    LlmAgent = None  # type: ignore


def plan_drive_sort(folder_id: str, max_chars: int = 60_000, supports_all_drives: bool = False) -> Dict[str, Any]:
    """
    Build a dry-run plan for sorting a Google Drive folder.
    Returns structured JSON so the agent can display/confirm.
    """
    plan = build_plan(
        folder_id=folder_id,
        local_path=None,
        max_chars=max_chars,
        supports_all_drives=supports_all_drives,
        model_summary="gemini-2.5-flash",
        model_folder="gemini-2.5-flash",
        model_critic="gemini-2.5-flash",
        critic_iterations=2,
        adk_timeout_seconds=120,
        emit_report=False,
    )
    return {"folder_id": folder_id, "actions": [a.__dict__ for a in plan.actions]}


if LlmAgent:
    root_agent = LlmAgent(
        name="smart_sorter_coordinator",
        model="gemini-2.5-pro",
        tools=[plan_drive_sort],
        instruction=(
            "You help a user sort a Google Drive folder.\n"
            "- Use plan_drive_sort to produce a dry-run plan.\n"
            "- Ask for confirmation before any write actions (this MVP only plans in-tool).\n"
        ),
    )
