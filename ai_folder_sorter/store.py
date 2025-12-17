from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


STORE_DIR_NAME = ".aifo"
PROFILES_FILE_NAME = "profiles.json"
LATEST_PLAN_FILE_NAME = "latest_plan.json"


@dataclass(frozen=True)
class StoredFileFingerprint:
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class StoredFileProfile:
    file_path: str  # target-relative (POSIX style)
    fingerprint: StoredFileFingerprint
    mime_type: Optional[str]
    text_chars: int
    summary: str
    subject_label: str
    keywords: list[str]
    skipped_reason: Optional[str] = None
    last_applied_destination: Optional[str] = None  # folder path relative to target, or "(root)"


def store_dir(target: Path) -> Path:
    return target / STORE_DIR_NAME


def ensure_store_dir(target: Path) -> Path:
    d = store_dir(target)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _fingerprint_for_path(path: Path) -> StoredFileFingerprint:
    st = path.stat()
    return StoredFileFingerprint(size=int(st.st_size), mtime_ns=int(st.st_mtime_ns))


def _normalize_rel_path(rel_path: str) -> str:
    rel_path = (rel_path or "").replace("\\", "/").strip().lstrip("/")
    if not rel_path:
        raise ValueError("Empty relative path.")
    return rel_path


def load_profiles(target: Path) -> dict[str, StoredFileProfile]:
    """
    Load profiles from `.aifo/profiles.json`.
    Returns dict keyed by file_path (target-relative, POSIX style).
    """
    p = store_dir(target) / PROFILES_FILE_NAME
    if not p.exists():
        return {}
    raw = p.read_text(encoding="utf-8", errors="ignore")
    if not raw.strip():
        return {}
    try:
        obj = json.loads(raw)
    except Exception:
        return {}

    profiles_obj = obj.get("profiles") if isinstance(obj, dict) else None
    if not isinstance(profiles_obj, dict):
        return {}

    out: dict[str, StoredFileProfile] = {}
    for k, v in profiles_obj.items():
        if not isinstance(v, dict):
            continue
        try:
            file_path = _normalize_rel_path(str(v.get("file_path") or k))
            fp = v.get("fingerprint") or {}
            fingerprint = StoredFileFingerprint(size=int(fp.get("size", 0)), mtime_ns=int(fp.get("mtime_ns", 0)))
            prof = StoredFileProfile(
                file_path=file_path,
                fingerprint=fingerprint,
                mime_type=(str(v.get("mime_type")).strip() or None) if v.get("mime_type") is not None else None,
                text_chars=int(v.get("text_chars", 0)),
                summary=str(v.get("summary", "")).strip(),
                subject_label=str(v.get("subject_label", "")).strip(),
                keywords=[str(x).strip() for x in (v.get("keywords") or []) if str(x).strip()],
                skipped_reason=str(v.get("skipped_reason")).strip() or None if v.get("skipped_reason") is not None else None,
                last_applied_destination=str(v.get("last_applied_destination")).strip() or None
                if v.get("last_applied_destination") is not None
                else None,
            )
            out[file_path] = prof
        except Exception:
            continue
    return out


def save_profiles(target: Path, profiles: dict[str, StoredFileProfile]) -> None:
    ensure_store_dir(target)
    p = store_dir(target) / PROFILES_FILE_NAME
    payload: dict[str, Any] = {"version": 1, "profiles": {}}
    for rel, prof in sorted(profiles.items(), key=lambda kv: kv[0].lower()):
        rel_norm = _normalize_rel_path(rel)
        payload["profiles"][rel_norm] = {
            "file_path": rel_norm,
            "fingerprint": {"size": prof.fingerprint.size, "mtime_ns": prof.fingerprint.mtime_ns},
            "mime_type": prof.mime_type,
            "text_chars": prof.text_chars,
            "summary": prof.summary,
            "subject_label": prof.subject_label,
            "keywords": list(prof.keywords),
            "skipped_reason": prof.skipped_reason,
            "last_applied_destination": prof.last_applied_destination,
        }
    _atomic_write_text(p, json.dumps(payload, ensure_ascii=False, indent=2))


def is_unchanged(*, existing: StoredFileProfile, path: Path) -> bool:
    try:
        fp = _fingerprint_for_path(path)
    except Exception:
        return False
    return fp.size == existing.fingerprint.size and fp.mtime_ns == existing.fingerprint.mtime_ns


def upsert_profile(
    *,
    profiles: dict[str, StoredFileProfile],
    rel_path: str,
    abs_path: Path,
    mime_type: Optional[str],
    text_chars: int,
    summary: str,
    subject_label: str,
    keywords: list[str],
    skipped_reason: Optional[str] = None,
) -> None:
    rel_norm = _normalize_rel_path(rel_path)
    fp = _fingerprint_for_path(abs_path)
    profiles[rel_norm] = StoredFileProfile(
        file_path=rel_norm,
        fingerprint=fp,
        mime_type=mime_type,
        text_chars=int(text_chars),
        summary=(summary or "").strip(),
        subject_label=(subject_label or "").strip(),
        keywords=[str(k).strip() for k in (keywords or []) if str(k).strip()],
        skipped_reason=(skipped_reason or "").strip() or None,
        last_applied_destination=profiles.get(rel_norm).last_applied_destination if rel_norm in profiles else None,
    )


def mark_applied_destination(
    *, profiles: dict[str, StoredFileProfile], rel_path: str, destination_folder: str
) -> None:
    rel_norm = _normalize_rel_path(rel_path)
    if rel_norm not in profiles:
        return
    existing = profiles[rel_norm]
    profiles[rel_norm] = StoredFileProfile(
        file_path=existing.file_path,
        fingerprint=existing.fingerprint,
        mime_type=existing.mime_type,
        text_chars=existing.text_chars,
        summary=existing.summary,
        subject_label=existing.subject_label,
        keywords=list(existing.keywords),
        skipped_reason=existing.skipped_reason,
        last_applied_destination=(destination_folder or "").strip() or "(root)",
    )


def move_profile_entry(
    *,
    profiles: dict[str, StoredFileProfile],
    old_rel_path: str,
    new_rel_path: str,
    new_abs_path: Path,
) -> None:
    old_rel_norm = _normalize_rel_path(old_rel_path)
    new_rel_norm = _normalize_rel_path(new_rel_path)
    if old_rel_norm not in profiles:
        return
    existing = profiles.pop(old_rel_norm)
    profiles[new_rel_norm] = StoredFileProfile(
        file_path=new_rel_norm,
        fingerprint=_fingerprint_for_path(new_abs_path),
        mime_type=existing.mime_type,
        text_chars=existing.text_chars,
        summary=existing.summary,
        subject_label=existing.subject_label,
        keywords=list(existing.keywords),
        skipped_reason=existing.skipped_reason,
        last_applied_destination=existing.last_applied_destination,
    )


def save_latest_plan(target: Path, plan: dict[str, Any]) -> None:
    ensure_store_dir(target)
    p = store_dir(target) / LATEST_PLAN_FILE_NAME
    _atomic_write_text(p, json.dumps(plan, ensure_ascii=False, indent=2, default=str))
