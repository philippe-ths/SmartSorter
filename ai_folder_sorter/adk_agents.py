from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

from google import genai

from .prompts import CRITIQUE_GLOBAL_PLAN, PLAN_GLOBAL, REPAIR_GLOBAL_PLAN, SUMMARIZE_FILE


@dataclass(frozen=True)
class Models:
    """Model configuration for different agent roles."""
    summariser: str
    critic: str
    planner: str
    repair: str


# =============================================================================
# LLM Client and Retry Logic
# =============================================================================

def _client(*, timeout_seconds: int) -> genai.Client:
    """Create a Gemini client with the specified timeout."""
    # google-genai expects http_options.timeout in milliseconds (min 10s enforced server-side).
    timeout_ms = max(int(timeout_seconds) * 1000, 10_000)
    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if api_key:
        return genai.Client(api_key=api_key, http_options={"timeout": timeout_ms})
    return genai.Client(http_options={"timeout": timeout_ms})


def _strip_markdown_code_block(text: str) -> str:
    """Strip markdown code block wrappers if present."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _call_json(
    model: str,
    instruction: str,
    payload: dict[str, Any],
    timeout_seconds: int,
    *,
    max_retries: int = 3,
    initial_delay: float = 1.0,
) -> dict[str, Any]:
    """
    Call the LLM and parse JSON response with retry logic.
    
    Args:
        model: The model identifier
        instruction: The system instruction
        payload: The input payload to send as JSON
        timeout_seconds: Timeout for the request
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay between retries (exponential backoff)
        
    Returns:
        Parsed JSON response as a dict
        
    Raises:
        RuntimeError: If all retries fail or response is invalid
    """
    client = _client(timeout_seconds=timeout_seconds)
    prompt = instruction.strip() + "\n\nINPUT JSON:\n" + json.dumps(payload, ensure_ascii=False)
    
    last_error: Optional[Exception] = None
    
    for attempt in range(max_retries):
        try:
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
            
            # Strip markdown code blocks if present (model sometimes ignores response_mime_type)
            text = _strip_markdown_code_block(text)
            
            try:
                result = json.loads(text)
                # Handle single-element array wrapping
                if isinstance(result, list) and len(result) == 1 and isinstance(result[0], dict):
                    result = result[0]
                if not isinstance(result, dict):
                    raise RuntimeError(f"Expected object, got {type(result).__name__}")
                return result
            except json.JSONDecodeError as e:
                raise RuntimeError(f"Model returned non-JSON: {text[:500]}") from e
                
        except Exception as e:
            last_error = e
            msg = str(e)
            
            # Don't retry on API key errors
            if "API key not valid" in msg or "API_KEY_INVALID" in msg:
                raise RuntimeError(
                    "Gemini API key is invalid. Set a valid `GOOGLE_API_KEY`, or configure ADC/Vertex auth for `google-genai`."
                ) from e
            
            # Don't retry on the last attempt
            if attempt < max_retries - 1:
                delay = initial_delay * (2 ** attempt)
                time.sleep(delay)
                continue
            
            raise RuntimeError(f"LLM call failed after {max_retries} attempts: {e}") from e
    
    # Should never reach here, but satisfy type checker
    raise RuntimeError(f"LLM call failed: {last_error}")


def summarize_file(*, model: str, file_name: str, text: str, timeout_seconds: int) -> dict[str, Any]:
    """
    Summarize a file's content using LLM.
    
    Args:
        model: The model identifier to use
        file_name: Name of the file being summarized
        text: Extracted text content from the file
        timeout_seconds: Timeout for the LLM call
        
    Returns:
        Dict with 'summary', 'subject_label', and 'keywords' keys
    """
    out = _call_json(
        model,
        SUMMARIZE_FILE.instruction,
        {"file_name": file_name, "text": text},
        timeout_seconds=timeout_seconds,
    )
    
    summary = str(out.get("summary", "")).strip()[:200]
    subject_label = str(out.get("subject_label", "")).strip()[:50]
    keywords = out.get("keywords") or []
    if not isinstance(keywords, list):
        keywords = []
    keywords = [str(k).strip() for k in keywords if str(k).strip()][:8]
    
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
    """
    Generate a global filing plan for the target folder.
    
    Args:
        model: The model identifier to use
        planning_snapshot: The complete planning context
        timeout_seconds: Timeout for the LLM call
        
    Returns:
        A dict with 'actions' and 'file_decisions' keys
    """
    return _call_json(
        model,
        PLAN_GLOBAL.instruction,
        planning_snapshot,
        timeout_seconds=timeout_seconds,
    )


def critique_global_plan(
    *,
    model: str,
    planning_snapshot: dict[str, Any],
    plan: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    """
    Critique a global filing plan.
    
    Args:
        model: The model identifier to use
        planning_snapshot: The planning context
        plan: The plan to critique
        timeout_seconds: Timeout for the LLM call
        
    Returns:
        A dict with 'acceptable', 'critique_rationale', and optional 'suggested_adjustments'
    """
    return _call_json(
        model,
        CRITIQUE_GLOBAL_PLAN.instruction,
        {"planning_snapshot": planning_snapshot, "plan": plan},
        timeout_seconds=timeout_seconds,
    )


def repair_global_plan(
    *,
    model: str,
    planning_snapshot: dict[str, Any],
    plan: dict[str, Any],
    critique: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    """
    Repair a global filing plan based on critic feedback.
    
    Args:
        model: The model identifier to use
        planning_snapshot: The planning context
        plan: The original plan
        critique: The critic's feedback
        timeout_seconds: Timeout for the LLM call
        
    Returns:
        A revised plan with the same schema as the original
    """
    return _call_json(
        model,
        REPAIR_GLOBAL_PLAN.instruction,
        {"planning_snapshot": planning_snapshot, "plan": plan, "critique": critique},
        timeout_seconds=timeout_seconds,
    )
