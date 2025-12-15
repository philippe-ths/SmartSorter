from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Optional

from google import genai


@dataclass(frozen=True)
class Models:
    summariser: str
    matcher: str
    critic: str


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
    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config={
            "response_mime_type": "application/json",
        },
    )
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
    instruction = """
You decide where to place a file into an existing folder or propose ONE new folder.

You MUST follow bounded specificity rules:
- Prefer existing folders by default.
- New folders must be plain-language, stable, human-recognisable categories (prefer plural nouns).
- Avoid entity-based names (people, companies), time-based names (years, quarters), and filetype buckets (PDFs, Images).
- Create a new folder only if it has strong recurring value.

Additional guidance for saved web content:
- If the content is a saved webpage / HTML source / view-source, prefer role-based buckets like "Websites", "Web Pages", "Company Profiles", or "Research".
- Do NOT create entity-named folders like "About Table of Content" or "Table of Content".
- Avoid vague non-noun folder names like "About".

Examples:
- Saved company homepage HTML -> "Websites" or "Company Profiles"
- Saved article / reference page -> "Research" or "Reference"

Return strict JSON:
{
  "file_name": "...",
  "target_folder": {"name": "...", "exists": true|false},
  "index_desc_if_new": "..." | null,
  "rationale": "..."
}

Return JSON only.
""".strip()
    payload: dict[str, Any] = {"file_profile": file_profile, "existing_folders": existing_folders}
    if critique_hint:
        payload["critique_hint"] = critique_hint
    out = _call_json(model, instruction, payload, timeout_seconds=timeout_seconds)
    if isinstance(out, list) and len(out) == 1 and isinstance(out[0], dict):
        out = out[0]
    if not isinstance(out, dict):
        raise RuntimeError(f"Expected object, got {type(out).__name__}")
    return out


def critique_plan(
    *,
    model: str,
    file_profile: dict[str, Any],
    file_plan: dict[str, Any],
    existing_folders: list[dict[str, Any]],
    timeout_seconds: int,
) -> dict[str, Any]:
    instruction = """
You are a critic that checks whether a placement plan is acceptable and low-surprise.

Acceptance guidance:
- Approve when the placement is what a reasonable human would expect.
- Reject when the folder is too specific, entity-based, or time-based, or when a better existing folder clearly fits,
  or when creating a new folder lacks strong recurring value.
- Reject vague non-noun folder names like "About" (prefer "Company Profiles" / "Websites" etc.).
  In particular for saved webpages / company homepages, prefer "Websites" or "Company Profiles" over "Projects" or "About".

Return strict JSON:
{
  "file_name": "...",
  "target_folder_name": "...",
  "acceptable": true|false,
  "critique_rationale": "...",
  "suggested_adjustments": {
    "action": "keep"|"use_existing_folder"|"create_new_folder"|"skip",
    "suggested_folder_name": "...",
    "suggested_index_desc_if_new": "...",
    "suggested_rationale": "..."
  } | null
}

Rules for suggested_adjustments:
- If action="use_existing_folder", suggested_folder_name MUST be exactly one of the provided existing folder names.
- Do not suggest entity-based folder names (companies/people) even if the file is about that entity.

Return JSON only.
""".strip()
    out = _call_json(
        model,
        instruction,
        {"file_profile": file_profile, "file_plan": file_plan, "existing_folders": existing_folders},
        timeout_seconds=timeout_seconds,
    )
    if isinstance(out, list) and len(out) == 1 and isinstance(out[0], dict):
        out = out[0]
    if not isinstance(out, dict):
        raise RuntimeError(f"Expected object, got {type(out).__name__}")
    return out
