from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


def parse_json_object_maybe(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {}

    m = _JSON_FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()

    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


_TYPE_BUCKETS = {
    "pdfs",
    "pdf",
    "images",
    "image",
    "photos",
    "photo",
    "docs",
    "documents",
    "spreadsheets",
    "slides",
    "presentations",
    "videos",
    "audio",
    "archives",
    "zips",
}


def is_bad_folder_name(name: str) -> bool:
    n = (name or "").strip()
    if not n:
        return True

    lower = n.lower()
    if lower in {"misc", "miscellaneous", "stuff", "important", "urgent", "new", "old"}:
        return True

    if any(ch.isdigit() for ch in n):
        return True

    if lower in _TYPE_BUCKETS:
        return True

    if len(n) > 60:
        return True

    return False


def normalize_folder_name(name: str) -> str:
    name = (name or "").strip()
    name = re.sub(r"\s+", " ", name)
    return name


def pick_fallback_folder(existing: list[str]) -> str:
    if "General" in existing:
        return "General"
    return "General"


def safe_get_str(obj: dict[str, Any], key: str) -> Optional[str]:
    v = obj.get(key)
    return v.strip() if isinstance(v, str) and v.strip() else None


_GOOGLE_ID_RE = re.compile(r"/d/([a-zA-Z0-9_-]+)|\\bid=([a-zA-Z0-9_-]+)")


def extract_google_id_from_stub(path: Path) -> Optional[str]:
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
        obj = json.loads(raw or "{}")
    except Exception:
        raw, obj = "", {}

    if isinstance(obj, dict):
        for k in ("id", "doc_id", "resource_id"):
            v = obj.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()

        for k in ("url", "open_url", "alternate_link", "alternateLink", "app_url"):
            v = obj.get(k)
            if isinstance(v, str) and v:
                m = _GOOGLE_ID_RE.search(v)
                if m:
                    return (m.group(1) or m.group(2) or "").strip() or None

    m = _GOOGLE_ID_RE.search(raw or "")
    if m:
        return (m.group(1) or m.group(2) or "").strip() or None

    return None
