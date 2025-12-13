from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

from .models import FolderDecision, Summary, TargetFolder
from .utils import normalize_folder_name, parse_json_object_maybe, safe_get_str


def _require_adk():
    try:
        from google.adk.agents import LlmAgent  # noqa: F401
        from google.adk.runners import InMemoryRunner  # noqa: F401
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Google ADK is not available. Install it (and configure model credentials) or run with --allow-fallback."
        ) from e


def preflight_adk_auth() -> None:
    """
    ADK's GoogleLLM uses google.genai.Client() without explicit args, so auth must
    be provided via environment variables.
    """
    api_key = (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY") or "").strip()
    use_vertex = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "0").strip().lower() in {"1", "true"}
    project = (os.environ.get("GOOGLE_CLOUD_PROJECT") or "").strip()
    location = (os.environ.get("GOOGLE_CLOUD_LOCATION") or "").strip()

    if api_key:
        return

    if use_vertex and (project or location):
        return

    raise RuntimeError(
        "ADK/LLM auth is not configured.\n"
        "- For Gemini API: set GOOGLE_API_KEY (or GEMINI_API_KEY).\n"
        "- For Vertex AI: set GOOGLE_GENAI_USE_VERTEXAI=1 and GOOGLE_CLOUD_PROJECT + GOOGLE_CLOUD_LOCATION "
        "(and have ADC configured).\n"
    )


async def _run_agent_once(*, agent: Any, state_delta: dict[str, Any], timeout_seconds: int) -> str:
    from google.adk.runners import InMemoryRunner, types

    runner = InMemoryRunner(agent, app_name="smart_sorter")
    runner.session_service.create_session_sync(app_name="smart_sorter", user_id="smart_sorter", session_id="default")
    last_text = ""
    agen = runner.run_async(
        user_id="smart_sorter",
        session_id="default",
        new_message=types.UserContent(parts=[types.Part(text="Run now.")]),
        state_delta=state_delta,
    )

    async def _consume() -> str:
        nonlocal last_text
        async for event in agen:
            if event.error_message:
                raise RuntimeError(event.error_message)
            content = getattr(event, "content", None)
            parts = getattr(content, "parts", None) if content else None
            if not parts:
                continue
            text_parts: list[str] = []
            for p in parts:
                t = getattr(p, "text", None)
                if isinstance(t, str) and t:
                    text_parts.append(t)
            if text_parts:
                last_text = "\n".join(text_parts).strip()
            if getattr(event, "turn_complete", False) and last_text:
                return last_text
        return last_text

    try:
        return await asyncio.wait_for(_consume(), timeout=timeout_seconds)
    except asyncio.TimeoutError as e:
        raise TimeoutError(f"ADK call timed out after {timeout_seconds}s") from e


def _run_agent_once_sync(*, agent: Any, state_delta: dict[str, Any], timeout_seconds: int) -> str:
    return asyncio.run(_run_agent_once(agent=agent, state_delta=state_delta, timeout_seconds=timeout_seconds))


def summarize_with_adk(
    *,
    model: str,
    filename: str,
    mime_type: str,
    text_snippet: str,
    metadata: dict[str, Any],
    timeout_seconds: int,
) -> Optional[Summary]:
    _require_adk()
    preflight_adk_auth()
    from google.adk.agents import LlmAgent

    agent = LlmAgent(
        name="summariser_agent",
        model=model,
        include_contents="none",
        instruction=(
            "You summarise a file for semantic filing.\n"
            "Input JSON:\n"
            "{file_json}\n\n"
            "Rules:\n"
            "- Ignore file type for subject; focus on topic/intent.\n"
            "- Output ONLY valid JSON with keys: summary, keywords, subject_label.\n"
            "- keywords must be a short list of strings.\n"
            "- subject_label should be 2-6 words.\n"
        ),
    )

    file_json = {
        "filename": filename,
        "mimeType": mime_type,
        "textSnippet": text_snippet,
        "metadata": metadata,
    }
    resp_text = _run_agent_once_sync(agent=agent, state_delta={"file_json": file_json}, timeout_seconds=timeout_seconds)
    obj = parse_json_object_maybe(resp_text)
    summary = safe_get_str(obj, "summary") or ""
    subject_label = safe_get_str(obj, "subject_label") or ""
    keywords = obj.get("keywords") if isinstance(obj.get("keywords"), list) else []
    keywords = [k.strip() for k in keywords if isinstance(k, str) and k.strip()]
    if not summary or not subject_label:
        return None
    return Summary(summary=summary, keywords=keywords, subject_label=subject_label)


def decide_folder_with_adk(
    *,
    model: str,
    file_profile: dict[str, Any],
    existing_folders: list[dict[str, str]],
    timeout_seconds: int,
) -> Optional[FolderDecision]:
    _require_adk()
    preflight_adk_auth()
    from google.adk.agents import LlmAgent

    agent = LlmAgent(
        name="folder_matcher_agent",
        model=model,
        include_contents="none",
        instruction=(
            "You choose a semantic folder for a file.\n"
            "Input JSON:\n"
            "{input_json}\n\n"
            "Rules:\n"
            "- Prefer existing folders; create new folders only as a last resort.\n"
            "- Foldering must be semantic (content/intent), never by file type (no 'PDFs', 'Images', etc.).\n"
            "- Avoid entity-based and time-based names (no people, companies, years, quarters).\n"
            "- Prefer plain-language, stable, role-based plural nouns (e.g., 'Agreements', 'Receipts', 'Plans').\n"
            "- Output ONLY valid JSON with keys: target_folder (object with keys: name, exists), "
            "index_description_if_new, rationale.\n"
        ),
    )

    input_json = {"file_profile": file_profile, "existing_folders": existing_folders}
    resp_text = _run_agent_once_sync(
        agent=agent, state_delta={"input_json": input_json}, timeout_seconds=timeout_seconds
    )
    obj = parse_json_object_maybe(resp_text)
    tf = obj.get("target_folder") if isinstance(obj.get("target_folder"), dict) else {}
    name = normalize_folder_name(safe_get_str(tf, "name") or "")
    exists_val = tf.get("exists")
    exists = bool(exists_val) if isinstance(exists_val, bool) else False
    index_desc = safe_get_str(obj, "index_description_if_new") or ""
    rationale = safe_get_str(obj, "rationale") or ""
    if not name:
        return None
    return FolderDecision(
        target_folder=TargetFolder(name=name, exists=exists),
        index_description_if_new=index_desc,
        rationale=rationale,
    )


def critique_plan_with_adk(
    *,
    model: str,
    draft_plan: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    """
    Reviews the entire draft plan and returns either approval or specific revisions.

    Expected output JSON:
      {
        "approved": true|false,
        "revised_assignments": [
          {
            "file_key": "...",
            "target_folder": {"name": "..."},
            "index_description_if_new": "...",
            "rationale": "..."
          }
        ],
        "notes": "..."
      }
    """
    _require_adk()
    preflight_adk_auth()
    from google.adk.agents import LlmAgent

    agent = LlmAgent(
        name="plan_critic_agent",
        model=model,
        include_contents="none",
        instruction=(
            "You are a critic reviewing a draft file-organisation plan.\n"
            "Input JSON:\n"
            "{draft_plan}\n\n"
            "Your job:\n"
            "- Enforce bounded specificity: prefer reusing existing/proposed folders; avoid creating many tiny folders.\n"
            "- Reject type buckets (PDFs/Images/etc), entity-based names (people/companies), and time-based names (years/quarters).\n"
            "- Prefer plain-language, stable, role-based plural nouns.\n"
            "- Keep folder counts reasonable (target ~7-12, soft cap ~15) by merging near-duplicates.\n\n"
            "Output ONLY valid JSON with keys:\n"
            "- approved (boolean)\n"
            "- revised_assignments (list; empty if approved). Each item must include: file_key, "
            "target_folder (object with key: name), index_description_if_new, rationale.\n"
            "- notes (string)\n"
            "Rules:\n"
            "- Only propose changes when clearly beneficial; otherwise set approved=true.\n"
            "- Do not invent file keys; use only file_key values from the input.\n"
        ),
    )

    resp_text = _run_agent_once_sync(
        agent=agent, state_delta={"draft_plan": draft_plan}, timeout_seconds=timeout_seconds
    )
    obj = parse_json_object_maybe(resp_text)
    if "approved" not in obj:
        return {}
    return obj if isinstance(obj, dict) else {}
