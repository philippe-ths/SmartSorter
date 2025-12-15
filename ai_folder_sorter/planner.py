from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from . import adk_agents
from .drive import google_preview_for_stub
from .models import Action, FileProfile, FilePlan, FolderProfile
from .utils import (
    extract_google_id_from_stub,
    extract_docx_text,
    extract_pdf_text,
    extract_xlsx_text,
    is_google_stub,
    is_ignorable_file_name,
    managed_index_update,
    read_text_file,
    sanitize_folder_name,
    sniff_mime_type,
)


def _log(enabled: bool, msg: str) -> None:
    if enabled:
        print(msg, flush=True)


def _extract_text(path: Path, *, max_chars: int, logging: bool) -> tuple[str, dict[str, Any]]:
    ext = path.suffix.lower()

    if is_google_stub(path):
        file_id = extract_google_id_from_stub(path)
        text, status = google_preview_for_stub(path, file_id=file_id, max_chars=max_chars)
        meta = {
            "method": "google-drive-export" if status.google_fetched else "google-stub",
            "truncated": False,
            "is_full_content": bool(status.google_fetched),
            "google_fetched": bool(status.google_fetched),
            "google_error": status.error,
            "google": asdict(status),
        }
        return text, meta

    if ext == ".pdf":
        text, truncated = extract_pdf_text(path, max_chars=max_chars)
        return text, {"method": "pdf-text", "truncated": truncated, "is_full_content": not truncated}

    if ext in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
        text, truncated = extract_xlsx_text(path, max_chars=max_chars)
        return text, {"method": "xlsx-cells", "truncated": truncated, "is_full_content": not truncated}

    if ext == ".docx":
        text, truncated = extract_docx_text(path, max_chars=max_chars)
        return text, {"method": "docx-text", "truncated": truncated, "is_full_content": not truncated}

    if ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".tiff", ".bmp", ".heic"}:
        return "", {"method": "image", "truncated": False, "is_full_content": False}

    text, truncated = read_text_file(path, max_chars=max_chars)
    return text, {"method": "text", "truncated": truncated, "is_full_content": not truncated}


def _folder_profiles(target: Path, *, max_index_chars: int = 800) -> list[FolderProfile]:
    profiles: list[FolderProfile] = []
    for p in sorted(target.iterdir(), key=lambda x: x.name.lower()):
        if not p.is_dir():
            continue
        idx = p / "_index.md"
        if idx.exists() and idx.is_file():
            raw = idx.read_text(encoding="utf-8", errors="ignore")
            desc = raw.strip().splitlines()[0:5]
            desc_text = " ".join([x.strip() for x in desc if x.strip()])[:max_index_chars] or None
            profiles.append(FolderProfile(name=p.name, desc=desc_text, has_index=True))
        else:
            profiles.append(FolderProfile(name=p.name, desc=None, has_index=False))
    return profiles


def build_local_plan(
    *,
    target: Path,
    models: adk_agents.Models,
    skip_files: int,
    max_files: int,
    max_chars: int,
    min_chars: int,
    critic_iterations: int,
    show_summaries: bool,
    logging: bool,
    adk_timeout_seconds: int,
) -> dict[str, Any]:
    if not target.exists() or not target.is_dir():
        raise ValueError(f"Target must be an existing directory: {target}")

    _log(logging, f"[init] Target: {str(target)}")
    _log(logging, f"[init] Models: summariser={models.summariser}, matcher={models.matcher}, critic={models.critic}")
    _log(logging, "[init] Mode: dry-run (apply=false)")

    all_files: list[Path] = []
    ignored_files: list[Path] = []
    subfolders: list[Path] = []
    for p in sorted(target.iterdir(), key=lambda x: x.name.lower()):
        if p.is_file():
            if is_ignorable_file_name(p.name):
                ignored_files.append(p)
            else:
                all_files.append(p)
        elif p.is_dir():
            subfolders.append(p)

    if skip_files < 0:
        raise ValueError("--skip-files must be >= 0")
    if max_files < 0:
        raise ValueError("--max-files must be >= 0")
    if skip_files >= len(all_files):
        files: list[Path] = []
    else:
        remaining = all_files[skip_files:]
        files = remaining if max_files == 0 else remaining[:max_files]

    if logging and ignored_files:
        _log(logging, f"[scan] Ignored files ({len(ignored_files)}):")
        for p in ignored_files[:50]:
            _log(logging, f"  - {p.name}")
        if len(ignored_files) > 50:
            _log(logging, f"  - ... ({len(ignored_files) - 50} more)")

    if skip_files:
        _log(logging, f"[scan] Skip files: {skip_files}")
    _log(logging, f"[scan] Files to process ({len(files)} of {len(all_files)}):")
    for p in files:
        _log(logging, f"  - {p.name}")
    _log(logging, f"[scan] Existing subfolders ({len(subfolders)}):")
    for p in subfolders:
        _log(logging, f"  - {p.name}")

    folder_profiles = _folder_profiles(target)
    _log(logging, f"[context] Folder profiles ({len(folder_profiles)}):")
    for fp in folder_profiles:
        if fp.has_index and fp.desc:
            _log(logging, f"  - {fp.name} (index: yes) desc: {fp.desc}")
        elif fp.has_index:
            _log(logging, f"  - {fp.name} (index: yes)")
        else:
            _log(logging, f"  - {fp.name} (index: no)")

    existing_folder_payload = [{"name": fp.name, "desc": fp.desc} for fp in folder_profiles]

    per_file: list[dict[str, Any]] = []
    actions: list[Action] = []
    folder_to_desc: dict[str, str] = {}
    moves: list[tuple[Path, str]] = []
    skipped: list[dict[str, Any]] = []

    for p in files:
        mime = sniff_mime_type(p)
        text, meta = _extract_text(p, max_chars=max_chars, logging=logging)
        text_chars = len(text)
        extra = ""
        if meta.get("method") in {"google-stub", "google-drive-export"}:
            if meta.get("google_error"):
                extra = f' error="{meta.get("google_error")}"'
            elif meta.get("google_fetched") is not None:
                extra = f" google_fetched={str(bool(meta.get('google_fetched'))).lower()}"
        _log(
            logging,
            f"[extract] {p.name} method={meta.get('method')} chars={text_chars} (truncated={bool(meta.get('truncated'))}){extra}",
        )
        # `min_chars` is primarily a safety check against extraction failures (e.g. scans, empty exports).
        # If we believe we have the file's full content (and it's simply short), still process it.
        is_full_content = bool(meta.get("is_full_content"))
        if text_chars < min_chars and not is_full_content:
            _log(logging, f'[skip] {p.name} reason="insufficient extracted text" chars={text_chars} min={min_chars}')
            skipped.append({"file_name": p.name, "file_path": str(p), "reason": "insufficient extracted text", "chars": text_chars})
            actions.append(
                Action(kind="skip_file", file_name=p.name, file_path=p, details={"reason": "insufficient extracted text", "chars": text_chars, "min": min_chars})
            )
            continue

        summary_obj = adk_agents.summarize_file(
            model=models.summariser,
            file_name=p.name,
            text=text,
            timeout_seconds=adk_timeout_seconds,
        )
        _log(
            logging,
            f'[summarise] {p.name} summary="{summary_obj.get("summary","")}" subject_label="{summary_obj.get("subject_label","")}" keywords={summary_obj.get("keywords",[])}',
        )

        file_profile = FileProfile(
            file_name=p.name,
            summary=summary_obj.get("summary", ""),
            subject_label=summary_obj.get("subject_label", ""),
            keywords=list(summary_obj.get("keywords") or []),
            mime_type=mime,
            text_chars=text_chars,
        )
        file_profile_payload = {"name": file_profile.file_name, "summary": file_profile.summary, "keywords": file_profile.keywords}

        # Critic loop runs only when not yet accepted, and caps total evaluations at 2 by default.
        max_total_iters = max(1, int(critic_iterations))
        max_total_iters = min(max_total_iters, 2)

        critique: Optional[dict[str, Any]] = None
        file_plan: Optional[dict[str, Any]] = None
        acceptable = False

        for iter_idx in range(1, max_total_iters + 1):
            if iter_idx == 1:
                file_plan = adk_agents.match_folder(
                    model=models.matcher,
                    file_profile=file_profile_payload,
                    existing_folders=existing_folder_payload,
                    critique_hint=None,
                    timeout_seconds=adk_timeout_seconds,
                )
                file_plan = _normalize_file_plan(file_plan=file_plan, file_name=p.name)
                _log_match(logging=logging, file_name=p.name, file_plan=file_plan)
            else:
                if critique is None:
                    break
                file_plan = _apply_or_rematch(
                    model=models.matcher,
                    file_profile=file_profile_payload,
                    existing_folders=existing_folder_payload,
                    critique=critique,
                    timeout_seconds=adk_timeout_seconds,
                    logging=logging,
                    iter_idx=iter_idx - 1,
                )

            critique = adk_agents.critique_plan(
                model=models.critic,
                file_profile=file_profile_payload,
                file_plan=file_plan,
                existing_folders=existing_folder_payload,
                timeout_seconds=adk_timeout_seconds,
            )
            acceptable = bool(critique.get("acceptable"))
            _log(
                logging,
                f'[critic] iter={iter_idx} {p.name} -> {file_plan["target_folder"]["name"]} acceptable={str(acceptable).lower()} critique_rationale="{critique.get("critique_rationale","")}"',
            )
            if acceptable:
                break

        if not file_plan or not acceptable:
            _log(logging, f'[skip] {p.name} reason="critic loop exhausted"')
            skipped.append({"file_name": p.name, "file_path": str(p), "reason": "critic loop exhausted"})
            actions.append(Action(kind="skip_file", file_name=p.name, file_path=p, details={"reason": "critic loop exhausted"}))
            continue

        final_folder = file_plan["target_folder"]["name"]
        is_new_folder = not bool(file_plan["target_folder"]["exists"])

        if is_new_folder:
            desc = str(file_plan.get("index_desc_if_new") or "").strip()
            if desc:
                folder_to_desc.setdefault(final_folder, desc)

        moves.append((p, final_folder))

        per_file.append(
            {
                "filename": p.name,
                "file_key": str(p),
                "mimeType": mime,
                "textChars": text_chars,
                "summary": asdict(file_profile),
                "decision_final": file_plan,
            }
        )

    # Aggregate actions.
    ensured: set[str] = set()
    for _, folder in moves:
        if folder not in ensured:
            ensured.add(folder)
            actions.append(Action(kind="ensure_folder", folder_name=folder, details={"reason": "Create folder (if missing)."}))
    for src, folder in moves:
        actions.append(
            Action(
                kind="move_file",
                folder_name=folder,
                file_path=src,
                file_name=src.name,
                details={"rationale": _find_file_rationale(per_file, src)},
            )
        )

    # Index markdown per touched folder.
    folder_files: dict[str, list[dict[str, str]]] = {}
    for item in per_file:
        folder = (item.get("decision_final") or {}).get("target_folder", {}).get("name")
        if not folder or folder == "(root)":
            continue
        folder_files.setdefault(folder, []).append(
            {"file_name": item["filename"], "summary": (item.get("summary") or {}).get("summary", "")}
        )

    for folder, files_list in folder_files.items():
        desc = folder_to_desc.get(folder)
        managed_md = _render_managed_index(folder_name=folder, desc=desc, files=files_list)
        actions.append(Action(kind="update_index", folder_name=folder, index_markdown=managed_md, details={"managed": True}))

    report = {
        "mode": "local",
        "target": str(target),
        "models": asdict(models),
        "actions": [asdict(a) for a in actions],
        "skipped": skipped,
    }

    if show_summaries:
        report["human_summary"] = _human_summary(
            existing_folders=folder_profiles,
            moves=moves,
            folder_to_desc=folder_to_desc,
        )

    _log_plan(logging=logging, moves=moves, ensured=sorted(ensured, key=str.lower))

    return report


def _normalize_file_plan(*, file_plan: dict[str, Any], file_name: str) -> dict[str, Any]:
    try:
        tgt = file_plan.get("target_folder") or {}
        tgt_name_raw = sanitize_folder_name(str(tgt.get("name", "")))
        exists = bool(tgt.get("exists"))
        file_plan["target_folder"] = {"name": tgt_name_raw, "exists": exists}
    except Exception:
        raise RuntimeError(f"Invalid folder match output for {file_name}: {json.dumps(file_plan)[:500]}")

    rationale = str(file_plan.get("rationale", "")).strip()
    if not rationale:
        file_plan["rationale"] = "No rationale provided."
    return file_plan


def _log_match(*, logging: bool, file_name: str, file_plan: dict[str, Any]) -> None:
    tgt = file_plan["target_folder"]
    if tgt["exists"]:
        _log(logging, f'[match] {file_name} -> {tgt["name"]} (exists=true) rationale="{file_plan["rationale"]}"')
    else:
        _log(
            logging,
            f'[match] {file_name} -> {tgt["name"]} (exists=false) new_index_desc="{file_plan.get("index_desc_if_new","")}" rationale="{file_plan["rationale"]}"',
        )

def _log_rematch(*, logging: bool, iter_idx: int, file_name: str, file_plan: dict[str, Any]) -> None:
    tgt = file_plan["target_folder"]
    if tgt["exists"]:
        _log(logging, f'[rematch] iter={iter_idx} {file_name} -> {tgt["name"]} (exists=true) rationale="{file_plan["rationale"]}"')
    else:
        _log(
            logging,
            f'[rematch] iter={iter_idx} {file_name} -> {tgt["name"]} (exists=false) new_index_desc="{file_plan.get("index_desc_if_new","")}" rationale="{file_plan["rationale"]}"',
        )


def _apply_or_rematch(
    *,
    model: str,
    file_profile: dict[str, Any],
    existing_folders: list[dict[str, Any]],
    critique: dict[str, Any],
    timeout_seconds: int,
    logging: bool,
    iter_idx: int,
) -> dict[str, Any]:
    suggested = critique.get("suggested_adjustments") or {}
    action = str(suggested.get("action") or "").strip()

    if action in {"use_existing_folder", "create_new_folder"} and suggested.get("suggested_folder_name"):
        folder_name = str(suggested.get("suggested_folder_name") or "").strip()
        folder_name = sanitize_folder_name(folder_name)
        exists = any((f.get("name") == folder_name) for f in existing_folders)
        if action == "use_existing_folder" and not exists:
            # Critic suggested an "existing" folder that doesn't exist; treat as a new folder suggestion.
            action = "create_new_folder"
        plan = {
            "file_name": file_profile.get("name", ""),
            "target_folder": {"name": folder_name, "exists": exists},
            "index_desc_if_new": str(suggested.get("suggested_index_desc_if_new") or "").strip() or None,
            "rationale": str(suggested.get("suggested_rationale") or "").strip() or "Adjusted per critic suggestion.",
        }
        _log_rematch(logging=logging, iter_idx=iter_idx, file_name=str(file_profile.get("name") or ""), file_plan=plan)
        return plan

    _log(logging, f"[rematch] iter={iter_idx} {file_profile.get('name','')} ...")
    plan = adk_agents.match_folder(
        model=model,
        file_profile=file_profile,
        existing_folders=existing_folders,
        critique_hint=critique,
        timeout_seconds=timeout_seconds,
    )
    plan = _normalize_file_plan(file_plan=plan, file_name=str(file_profile.get("name") or ""))
    _log_rematch(logging=logging, iter_idx=iter_idx, file_name=str(file_profile.get("name") or ""), file_plan=plan)
    return plan


def _log_plan(*, logging: bool, moves: list[tuple[Path, str]], ensured: list[str]) -> None:
    if not logging:
        return
    _log(logging, "[plan] Create folders:")
    for f in ensured:
        _log(logging, f"  - {f}")
    _log(logging, "[plan] Moves:")
    for src, folder in moves:
        _log(logging, f"  - {src.name} -> {folder}/")
    _log(logging, "[plan] Leave in root:")
    _log(logging, "  - (none)")


def _find_file_rationale(per_file: list[dict[str, Any]], src: Path) -> str:
    for item in per_file:
        if item.get("filename") == src.name:
            df = item.get("decision_final") or {}
            return str(df.get("rationale") or "").strip()
    return ""


def _render_managed_index(*, folder_name: str, desc: Optional[str], files: list[dict[str, str]]) -> str:
    header = f"# {folder_name}\n"
    desc_line = (desc or "").strip()
    if desc_line:
        body = f"\n{desc_line}\n\n## Managed Index\n"
    else:
        body = "\n## Managed Index\n"
    lines = [header + body, "This section is managed by SmartSorter.\n", "### Recently filed\n"]
    for f in files:
        fn = f.get("file_name", "")
        summ = (f.get("summary") or "").strip()
        if summ:
            lines.append(f"- {fn}: {summ}\n")
        else:
            lines.append(f"- {fn}\n")
    return "".join(lines).strip() + "\n"


def _human_summary(
    *,
    existing_folders: list[FolderProfile],
    moves: list[tuple[Path, str]],
    folder_to_desc: dict[str, str],
    leave_in_root: list[dict[str, Any]] | None = None,
) -> str:
    existing_names = sorted([f.name for f in existing_folders], key=str.lower)
    new_folders = sorted({folder for _, folder in moves if folder not in set(existing_names)}, key=str.lower)
    lines: list[str] = []
    lines.append("Folders (existing) and what they should contain:\n")
    if existing_names:
        for n in existing_names:
            lines.append(f"- {n}\n")
    else:
        lines.append("- (none found)\n")
    lines.append("\nFolders (new) and what they should contain:\n")
    if new_folders:
        for n in new_folders:
            suffix = f": {folder_to_desc.get(n)}" if folder_to_desc.get(n) else ""
            lines.append(f"- {n}{suffix}\n")
    else:
        lines.append("- (none)\n")
    lines.append("\nMoves:\n")
    for src, folder in moves:
        lines.append(f"- {src.name} -> {folder}/\n")
    if leave_in_root:
        lines.append("\nLeave in root:\n")
        for item in leave_in_root:
            fn = item.get("file_name")
            reason = item.get("reason") or ""
            if reason:
                lines.append(f'- {fn} (reason="{reason}")\n')
            else:
                lines.append(f"- {fn}\n")
    return "".join(lines).strip()


def apply_local_plan(*, target: Path, report: dict[str, Any], logging: bool) -> None:
    actions = report.get("actions") or []
    for a in actions:
        kind = a.get("kind")
        if kind == "ensure_folder":
            folder = sanitize_folder_name(a.get("folder_name") or "")
            p = target / folder
            if not p.exists():
                _log(logging, f"[apply] Create folder: {folder}/")
                p.mkdir(parents=False, exist_ok=True)
        elif kind == "move_file":
            folder = sanitize_folder_name(a.get("folder_name") or "")
            src = Path(a.get("file_path") or "")
            dest = target / folder / src.name
            if src.exists() and src.is_file():
                _log(logging, f"[apply] Move: {src.name} -> {folder}/")
                shutil.move(str(src), str(dest))
        elif kind == "update_index":
            folder = sanitize_folder_name(a.get("folder_name") or "")
            idx = target / folder / "_index.md"
            managed_md = str(a.get("index_markdown") or "")
            existing = idx.read_text(encoding="utf-8", errors="ignore") if idx.exists() else ""
            updated = managed_index_update(existing, managed_md)
            _log(logging, f"[apply] Update index: {folder}/_index.md (managed section)")
            idx.write_text(updated, encoding="utf-8")
