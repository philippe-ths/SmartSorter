from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Optional

from google import genai


@dataclass(frozen=True)
class Models:
    summariser: str
    critic: str
    planner: str
    repair: str


def _client(*, timeout_seconds: int) -> genai.Client:
    # google-genai expects http_options.timeout in milliseconds (min 10s enforced server-side).
    timeout_ms = max(int(timeout_seconds) * 1000, 10_000)
    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if api_key:
        return genai.Client(api_key=api_key, http_options={"timeout": timeout_ms})
    return genai.Client(http_options={"timeout": timeout_ms})


def _call_json(model: str, instruction: str, payload: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    client = _client(timeout_seconds=timeout_seconds)
    prompt = instruction.strip() + "\n\nINPUT JSON:\n" + json.dumps(payload, ensure_ascii=False)
    try:
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
            },
        )
    except Exception as e:
        msg = str(e)
        if "API key not valid" in msg or "API_KEY_INVALID" in msg:
            raise RuntimeError(
                "Gemini API key is invalid. Set a valid `GOOGLE_API_KEY`, or configure ADC/Vertex auth for `google-genai`."
            ) from e
        raise RuntimeError(f"LLM call failed: {e}") from e
    text = (resp.text or "").strip()
    if not text:
        raise RuntimeError("Empty model response.")
    try:
        return json.loads(text)
    except Exception as e:
        raise RuntimeError(f"Model returned non-JSON: {text[:500]}") from e


def summarize_file(*, model: str, file_name: str, text: str, timeout_seconds: int) -> dict[str, Any]:
    instruction = """
You summarise a file into a strict JSON object with keys:
- summary: string, max 200 characters
- subject_label: string, max 50 characters
- keywords: array of 5 to 8 short words/phrases

Rules:
- Base the result ONLY on the provided extracted text. Do not guess from file name, path, or metadata.
- Keep it concise and factual.
- Return JSON only.
""".strip()
    out = _call_json(model, instruction, {"file_name": file_name, "text": text}, timeout_seconds=timeout_seconds)
    if isinstance(out, list) and len(out) == 1 and isinstance(out[0], dict):
        out = out[0]
    summary = str(out.get("summary", "")).strip()
    subject_label = str(out.get("subject_label", "")).strip()
    keywords = out.get("keywords") or []
    if not isinstance(keywords, list):
        keywords = []
    keywords = [str(k).strip() for k in keywords if str(k).strip()]
    summary = summary[:200]
    subject_label = subject_label[:50]
    if len(keywords) < 5:
        keywords = keywords[:8]
    else:
        keywords = keywords[:8]
    return {"summary": summary, "subject_label": subject_label, "keywords": keywords}


def match_folder(
    *,
    model: str,
    file_profile: dict[str, Any],
    existing_folders: list[dict[str, Any]],
    critique_hint: Optional[dict[str, Any]],
    timeout_seconds: int,
) -> dict[str, Any]:
    raise NotImplementedError("Per-file matching has been replaced by global planning. Use plan_global().")


def critique_plan(
    *,
    model: str,
    file_profile: dict[str, Any],
    file_plan: dict[str, Any],
    existing_folders: list[dict[str, Any]],
    timeout_seconds: int,
) -> dict[str, Any]:
    raise NotImplementedError("Per-file critique has been replaced by global plan critique. Use critique_global_plan().")


def plan_global(*, model: str, planning_snapshot: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    instruction = """
You generate a single GLOBAL filing plan for a target folder.

Goal:
- Produce predictable, low-surprise placements and stable folders.
- Prefer existing folders. Create new folders only when they have strong recurring value.
- If strong subtopic clusters exist inside a folder, you MAY propose a split by creating a subfolder inside that folder and moving all cluster members.

Rules:
- Do NOT delete anything.
- Do NOT rename existing folders.
- Do NOT modify file contents.
- Do NOT guess from filenames or timestamps; use only the provided planning snapshot (stored profiles and folder context).
- Folder names must be plain-language, stable categories (prefer plural nouns).
- Avoid entity-based names (people/companies), time-based names (years/quarters), and filetype buckets (PDFs, Images).

Return strict JSON ONLY with this schema:
{
  "actions": [
    {"kind": "create_folder", "path": "Folder/Subfolder", "index_desc": "..." | null},
    {"kind": "move_file", "from": "rel/path/to/file.ext", "to_folder": "Folder/Subfolder" | "(root)", "rationale": "..."},
    {"kind": "update_index", "folder_path": "Folder/Subfolder"}
  ],
  "file_decisions": [
    {"file_path": "rel/path/to/file.ext", "destination_folder_path": "Folder/Subfolder" | "(root)", "rationale": "..."}
  ]
}
""".strip()
    out = _call_json(model, instruction, planning_snapshot, timeout_seconds=timeout_seconds)
    if isinstance(out, list) and len(out) == 1 and isinstance(out[0], dict):
        out = out[0]
    if not isinstance(out, dict):
        raise RuntimeError(f"Expected object, got {type(out).__name__}")
    return out


def critique_global_plan(
    *,
    model: str,
    planning_snapshot: dict[str, Any],
    plan: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    instruction = """
You are a critic that checks whether a GLOBAL filing plan is acceptable and low-surprise.

Acceptance guidance:
- Approve when the plan matches what a reasonable human would expect and avoids churn.
- Reject when:
  - the plan creates folders that are too specific, entity-based, time-based, or redundant,
  - a split is proposed without strong recurring value (cluster too small or not clearly narrower than parent),
  - moves feel arbitrary or unstable.

Return strict JSON ONLY:
{
  "acceptable": true|false,
  "critique_rationale": "...",
  "suggested_adjustments": [
    {"kind": "remove_action", "action_index": 0, "reason": "..."},
    {"kind": "rename_new_folder", "old_path": "A/B", "new_path": "A/C", "reason": "..."},
    {"kind": "change_destination", "file_path": "rel/path.ext", "new_destination_folder_path": "(root)" | "X/Y", "reason": "..."}
  ] | null
}
""".strip()
    out = _call_json(
        model,
        instruction,
        {"planning_snapshot": planning_snapshot, "plan": plan},
        timeout_seconds=timeout_seconds,
    )
    if isinstance(out, list) and len(out) == 1 and isinstance(out[0], dict):
        out = out[0]
    if not isinstance(out, dict):
        raise RuntimeError(f"Expected object, got {type(out).__name__}")
    return out


def repair_global_plan(
    *,
    model: str,
    planning_snapshot: dict[str, Any],
    plan: dict[str, Any],
    critique: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    instruction = """
You repair a GLOBAL filing plan using critic feedback.

Inputs:
- planning_snapshot (context)
- plan (original plan)
- critique (critic feedback with suggested_adjustments)

Output:
- Return a revised plan with the exact same schema as the original plan:
{
  "actions": [...],
  "file_decisions": [...]
}

Rules:
- Apply critic guidance where reasonable.
- Keep changes minimal while making the plan acceptable and low-surprise.
- Return JSON only.
""".strip()
    out = _call_json(
        model,
        instruction,
        {"planning_snapshot": planning_snapshot, "plan": plan, "critique": critique},
        timeout_seconds=timeout_seconds,
    )
    if isinstance(out, list) and len(out) == 1 and isinstance(out[0], dict):
        out = out[0]
    if not isinstance(out, dict):
        raise RuntimeError(f"Expected object, got {type(out).__name__}")
    return out
