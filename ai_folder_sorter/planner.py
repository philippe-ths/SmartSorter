from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional

from . import adk_agents
from .clustering import FileForClustering, detect_keyword_clusters
from .models import Action, FolderProfile
from .store import STORE_DIR_NAME, load_profiles, mark_applied_destination, move_profile_entry, save_latest_plan, save_profiles, upsert_profile, is_unchanged
from .utils import (
    extract_docx_text,
    extract_pdf_text,
    extract_xlsx_text,
    is_ignorable_file_name,
    managed_index_update,
    read_text_file,
    sanitize_folder_name,
    sniff_mime_type,
)


def _log(enabled: bool, msg: str) -> None:
    if enabled:
        print(msg, flush=True)


def _rel_posix(target: Path, path: Path) -> str:
    return path.relative_to(target).as_posix()


def _folder_path_for_rel(rel_path: str) -> str:
    rel_path = rel_path.replace("\\", "/").lstrip("/")
    if "/" not in rel_path:
        return "(root)"
    return rel_path.rsplit("/", 1)[0]


def _sanitize_folder_path(path: str) -> str:
    raw = (path or "").strip()
    if raw in {"", ".", "(root)"}:
        return "(root)"
    parts = [p for p in raw.replace("\\", "/").split("/") if p and p not in {".", ".."}]
    safe = [sanitize_folder_name(p) for p in parts]
    return "/".join(safe)


def _safe_join_under_target(target: Path, rel_path: str) -> Path:
    rel_path = rel_path.replace("\\", "/").lstrip("/")
    p = (target / rel_path).resolve()
    target_resolved = target.resolve()
    if target_resolved == p or target_resolved in p.parents:
        return p
    raise ValueError(f"Path escapes target: {rel_path}")


def _extract_text(path: Path, *, max_chars: int) -> tuple[str, dict[str, Any]]:
    ext = path.suffix.lower()

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
    # If we read the whole file (not truncated), treat it as full content even if it is short.
    return text, {"method": "text", "truncated": truncated, "is_full_content": not truncated}


def _list_bounded_inventory(
    target: Path,
    *,
    include_depth2: bool = True,
) -> tuple[list[Path], list[Path]]:
    """
    Returns (files, folders), both absolute Paths.

    Bounded traversal:
    - Always includes: files in target root, and files in each direct subfolder.
    - If include_depth2: includes files in each direct subfolder's direct subfolders.
    """
    files: list[Path] = []
    folders: list[Path] = []

    for child in sorted(target.iterdir(), key=lambda p: p.name.lower()):
        if child.name == STORE_DIR_NAME:
            continue
        if child.is_file():
            if not is_ignorable_file_name(child.name):
                files.append(child)
            continue
        if not child.is_dir():
            continue
        if is_ignorable_file_name(child.name):
            continue
        folders.append(child)

        for p in sorted(child.iterdir(), key=lambda p: p.name.lower()):
            if p.is_file():
                if not is_ignorable_file_name(p.name):
                    files.append(p)
            elif include_depth2 and p.is_dir():
                if is_ignorable_file_name(p.name) or p.name == STORE_DIR_NAME:
                    continue
                folders.append(p)
                for q in sorted(p.iterdir(), key=lambda q: q.name.lower()):
                    if q.is_file() and not is_ignorable_file_name(q.name):
                        files.append(q)

    return files, folders


def _folder_profiles(target: Path, folders: list[Path], *, max_index_chars: int = 800) -> list[FolderProfile]:
    profiles: list[FolderProfile] = []
    for folder in sorted(folders, key=lambda p: _rel_posix(target, p).lower()):
        idx = folder / "_index.md"
        if idx.exists() and idx.is_file():
            raw = idx.read_text(encoding="utf-8", errors="ignore")
            desc = raw.strip().splitlines()[0:5]
            desc_text = " ".join([x.strip() for x in desc if x.strip()])[:max_index_chars] or None
            profiles.append(
                FolderProfile(folder_path=_rel_posix(target, folder), name=folder.name, desc=desc_text, has_index=True)
            )
        else:
            profiles.append(FolderProfile(folder_path=_rel_posix(target, folder), name=folder.name, desc=None, has_index=False))
    return profiles


def _render_managed_index(*, folder_path: str, desc: Optional[str], files: list[dict[str, str]]) -> str:
    folder_name = folder_path.split("/")[-1] if "/" in folder_path else folder_path
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


def _human_summary(*, moves: list[dict[str, str]], created_folders: list[str], skipped: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    lines.append("Create folders:\n")
    if created_folders:
        for f in created_folders:
            lines.append(f"- {f}/\n")
    else:
        lines.append("- (none)\n")

    lines.append("\nMoves:\n")
    if moves:
        for m in moves:
            lines.append(f'- {m["from"]} -> {m["to_folder"]}/\n' if m["to_folder"] != "(root)" else f'- {m["from"]} -> (root)\n')
    else:
        lines.append("- (none)\n")

    if skipped:
        lines.append("\nSkipped:\n")
        for s in skipped:
            reason = s.get("reason") or ""
            if reason:
                lines.append(f'- {s.get("file_path")} (reason="{reason}")\n')
            else:
                lines.append(f'- {s.get("file_path")}\n')
    return "".join(lines).strip()


def _normalize_plan(*, plan: dict[str, Any], inventory_rel_paths: set[str]) -> dict[str, Any]:
    actions = plan.get("actions") or []
    file_decisions = plan.get("file_decisions") or []

    if not isinstance(actions, list):
        actions = []
    if not isinstance(file_decisions, list):
        file_decisions = []

    norm_actions: list[dict[str, Any]] = []
    for a in actions:
        if not isinstance(a, dict):
            continue
        kind = str(a.get("kind") or "").strip()
        if kind == "create_folder":
            p = _sanitize_folder_path(str(a.get("path") or ""))
            if p == "(root)":
                continue
            norm_actions.append({"kind": "create_folder", "path": p, "index_desc": (str(a.get("index_desc") or "").strip() or None)})
        elif kind == "move_file":
            src = str(a.get("from") or "").replace("\\", "/").lstrip("/")
            if not src or src not in inventory_rel_paths:
                continue
            to_folder = _sanitize_folder_path(str(a.get("to_folder") or "(root)"))
            norm_actions.append(
                {
                    "kind": "move_file",
                    "from": src,
                    "to_folder": to_folder,
                    "rationale": str(a.get("rationale") or "").strip() or "No rationale provided.",
                }
            )
        elif kind == "update_index":
            folder_path = _sanitize_folder_path(str(a.get("folder_path") or ""))
            if folder_path == "(root)":
                continue
            norm_actions.append({"kind": "update_index", "folder_path": folder_path})

    norm_decisions: list[dict[str, Any]] = []
    for d in file_decisions:
        if not isinstance(d, dict):
            continue
        fp = str(d.get("file_path") or "").replace("\\", "/").lstrip("/")
        if not fp or fp not in inventory_rel_paths:
            continue
        dest = _sanitize_folder_path(str(d.get("destination_folder_path") or "(root)"))
        norm_decisions.append(
            {
                "file_path": fp,
                "destination_folder_path": dest,
                "rationale": str(d.get("rationale") or "").strip() or "No rationale provided.",
            }
        )

    return {"actions": norm_actions, "file_decisions": norm_decisions}


def build_local_plan(
    *,
    target: Path,
    models: adk_agents.Models,
    max_chars: int,
    min_chars: int,
    min_cluster_size: int,
    critic_iterations: int,
    show_summaries: bool,
    logging: bool,
    adk_timeout_seconds: int,
) -> dict[str, Any]:
    if not target.exists() or not target.is_dir():
        raise ValueError(f"Target must be an existing directory: {target}")

    # Mandatory store.
    (target / STORE_DIR_NAME).mkdir(parents=True, exist_ok=True)

    _log(logging, f"[init] Target: {str(target)}")
    _log(
        logging,
        f"[init] Models: summariser={models.summariser}, planner={models.planner}, critic={models.critic}, repair={models.repair}",
    )
    _log(logging, "[init] Mode: dry-run (apply=false)")

    inventory_files, inventory_folders = _list_bounded_inventory(target, include_depth2=True)
    inventory_rel = [_rel_posix(target, p) for p in inventory_files]
    inventory_rel_set = set(inventory_rel)

    root_files = [p for p in inventory_rel if "/" not in p]
    _log(logging, f"[scan] Root files to consider ({len(root_files)}):")
    for p in sorted(root_files, key=str.lower)[:80]:
        _log(logging, f"  - {p}")
    if len(root_files) > 80:
        _log(logging, f"  - ... ({len(root_files) - 80} more)")

    direct_subfolders = [p for p in inventory_folders if p.parent == target]
    _log(logging, f"[scan] Direct subfolders ({len(direct_subfolders)}):")
    for d in sorted(direct_subfolders, key=lambda p: p.name.lower()):
        _log(logging, f"  - {d.name}")
    _log(logging, f"[scan] Depth-1+ files to consider ({len(inventory_files)})")

    folder_profiles = _folder_profiles(target, inventory_folders)
    if logging:
        _log(logging, f"[context] Folder profiles ({len(folder_profiles)}):")
        for fp in folder_profiles[:80]:
            desc = f" desc: {fp.desc}" if fp.desc else ""
            _log(logging, f"  - {fp.folder_path} (index: {'yes' if fp.has_index else 'no'}){desc}")

    profiles = load_profiles(target)
    cached = 0
    needs = 0
    for p in inventory_files:
        rel = _rel_posix(target, p)
        existing = profiles.get(rel)
        if existing and is_unchanged(existing=existing, path=p):
            cached += 1
        else:
            needs += 1
    _log(logging, f"[store] Loaded profiles: {len(profiles)}")
    _log(logging, f"[store] Needs summarise: {needs} (cached={cached})")

    skipped: list[dict[str, Any]] = []
    files_for_planning: list[dict[str, Any]] = []
    files_for_cluster: list[FileForClustering] = []

    for p in sorted(inventory_files, key=lambda x: _rel_posix(target, x).lower()):
        rel = _rel_posix(target, p)
        mime = sniff_mime_type(p)
        existing = profiles.get(rel)

        if existing and is_unchanged(existing=existing, path=p) and existing.skipped_reason:
            skipped.append({"file_path": rel, "reason": existing.skipped_reason, "cached": True})
            continue

        if existing and is_unchanged(existing=existing, path=p) and not existing.skipped_reason:
            files_for_planning.append(
                {
                    "file_path": rel,
                    "current_folder_path": _folder_path_for_rel(rel),
                    "file_profile": {
                        "summary": existing.summary,
                        "subject_label": existing.subject_label,
                        "keywords": list(existing.keywords),
                    },
                }
            )
            files_for_cluster.append(
                FileForClustering(
                    file_path=rel,
                    folder_path=_folder_path_for_rel(rel),
                    keywords=list(existing.keywords),
                    subject_label=existing.subject_label,
                )
            )
            continue

        text, meta = _extract_text(p, max_chars=max_chars)
        text_chars = len(text)
        _log(logging, f"[extract] {rel} method={meta.get('method')} chars={text_chars} (truncated={bool(meta.get('truncated'))})")

        is_full_content = bool(meta.get("is_full_content"))
        if text_chars < min_chars and not is_full_content:
            reason = "insufficient extracted text"
            _log(logging, f'[skip] {rel} reason="{reason}" chars={text_chars} min={min_chars}')
            upsert_profile(
                profiles=profiles,
                rel_path=rel,
                abs_path=p,
                mime_type=mime,
                text_chars=text_chars,
                summary="",
                subject_label="",
                keywords=[],
                skipped_reason=reason,
            )
            skipped.append({"file_path": rel, "reason": reason, "chars": text_chars})
            continue

        summary_obj = adk_agents.summarize_file(
            model=models.summariser,
            file_name=p.name,
            text=text,
            timeout_seconds=adk_timeout_seconds,
        )
        _log(
            logging,
            f'[summarise] {rel} summary="{summary_obj.get("summary","")}" subject_label="{summary_obj.get("subject_label","")}" keywords={summary_obj.get("keywords",[])}',
        )

        upsert_profile(
            profiles=profiles,
            rel_path=rel,
            abs_path=p,
            mime_type=mime,
            text_chars=text_chars,
            summary=str(summary_obj.get("summary") or ""),
            subject_label=str(summary_obj.get("subject_label") or ""),
            keywords=list(summary_obj.get("keywords") or []),
            skipped_reason=None,
        )

        files_for_planning.append(
            {
                "file_path": rel,
                "current_folder_path": _folder_path_for_rel(rel),
                "file_profile": {
                    "summary": str(summary_obj.get("summary") or ""),
                    "subject_label": str(summary_obj.get("subject_label") or ""),
                    "keywords": list(summary_obj.get("keywords") or []),
                },
            }
        )
        files_for_cluster.append(
            FileForClustering(
                file_path=rel,
                folder_path=_folder_path_for_rel(rel),
                keywords=list(summary_obj.get("keywords") or []),
                subject_label=str(summary_obj.get("subject_label") or ""),
            )
        )

        # Save incrementally to avoid losing progress on crash/interrupt
        if len(files_for_planning) % 5 == 0:
            save_profiles(target, profiles)

    # Store is mandatory: persist profiles even for dry-runs.
    save_profiles(target, profiles)

    _log(logging, f"[global] Files with profiles: {len(files_for_planning)}")
    _log(logging, f"[global] Skipped (no usable text): {len(skipped)}")

    # Dynamic cluster sizing if set to 0 (auto)
    effective_min_cluster = min_cluster_size
    if effective_min_cluster <= 0:
        n_files = len(files_for_planning)
        if n_files < 20:
            effective_min_cluster = 2
        elif n_files < 100:
            effective_min_cluster = 3
        else:
            effective_min_cluster = 5
        _log(logging, f"[cluster] Dynamic sizing: n={n_files} -> min_cluster_size={effective_min_cluster}")

    clusters = detect_keyword_clusters(files_for_cluster, min_cluster_size=effective_min_cluster)
    if logging:
        by_folder: dict[str, list[dict[str, Any]]] = {}
        for c in clusters:
            by_folder.setdefault(c.folder_path, []).append({"label": c.label, "size": c.size, "members": c.members})
        for folder_path, cs in list(by_folder.items())[:30]:
            _log(logging, f"[cluster] Folder={folder_path} strong_clusters={len(cs)}")
            for c in cs[:3]:
                _log(logging, f'  - "{c["label"]}" size={c["size"]}')

    planning_snapshot: dict[str, Any] = {
        "target": str(target),
        "rules": {
            "no_deletions": True,
            "no_renames": True,
            "bounded_depth": 2,
            "min_cluster_size": int(effective_min_cluster),
        },
        "folders": [{"folder_path": f.folder_path, "name": f.name, "desc": f.desc, "has_index": f.has_index} for f in folder_profiles],
        "files": files_for_planning,
        "clusters": [asdict(c) for c in clusters[:100]],
    }

    plan_raw = adk_agents.plan_global(model=models.planner, planning_snapshot=planning_snapshot, timeout_seconds=adk_timeout_seconds)
    plan = _normalize_plan(plan=plan_raw, inventory_rel_paths=inventory_rel_set)

    critique: Optional[dict[str, Any]] = None
    acceptable = False
    max_iters = max(1, int(critic_iterations))
    max_iters = min(max_iters, 5)

    for iter_idx in range(1, max_iters + 1):
        critique = adk_agents.critique_global_plan(
            model=models.critic,
            planning_snapshot=planning_snapshot,
            plan=plan,
            timeout_seconds=adk_timeout_seconds,
        )
        acceptable = bool(critique.get("acceptable"))
        _log(logging, f'[critic] iter={iter_idx} acceptable={str(acceptable).lower()} rationale="{critique.get("critique_rationale","")}"')
        if acceptable:
            break
        if iter_idx >= max_iters:
            break
        plan_repaired = adk_agents.repair_global_plan(
            model=models.repair,
            planning_snapshot=planning_snapshot,
            plan=plan,
            critique=critique,
            timeout_seconds=adk_timeout_seconds,
        )
        plan = _normalize_plan(plan=plan_repaired, inventory_rel_paths=inventory_rel_set)
        _log(logging, f"[repair] iter={iter_idx} updated plan")

    # Always save latest plan + critique for inspection.
    save_latest_plan(target, {"planning_snapshot": planning_snapshot, "plan": plan, "critique": critique, "accepted": acceptable})

    report: dict[str, Any] = {
        "mode": "local",
        "target": str(target),
        "store_dir": str(target / STORE_DIR_NAME),
        "models": asdict(models),
        "accepted": acceptable,
        "critique": critique,
        "skipped": skipped,
        "global_plan": plan,
        "actions": [],
    }

    if not acceptable:
        if show_summaries:
            report["human_summary"] = _human_summary(moves=[], created_folders=[], skipped=skipped)
        return report

    # Build execution actions from plan.
    created_folders: list[str] = []
    moves: list[dict[str, str]] = []
    folder_desc: dict[str, str] = {}

    for a in plan.get("actions") or []:
        if a.get("kind") == "create_folder":
            created_folders.append(a["path"])
            if a.get("index_desc"):
                folder_desc[a["path"]] = str(a.get("index_desc") or "").strip()
        elif a.get("kind") == "move_file":
            moves.append({"from": a["from"], "to_folder": a["to_folder"], "rationale": a.get("rationale") or ""})

    # Ensure create_folder actions are first and unique.
    create_unique = sorted(set(created_folders), key=str.lower)
    actions: list[Action] = []
    for folder_path in create_unique:
        actions.append(Action(kind="create_folder", folder_name=folder_path, details={"index_desc": folder_desc.get(folder_path)}))

    # Map file decisions for deterministic move list (even if plan omitted move actions).
    decision_map: dict[str, dict[str, Any]] = {}
    for d in plan.get("file_decisions") or []:
        decision_map[str(d.get("file_path") or "")] = d

    for rel in sorted(inventory_rel_set, key=str.lower):
        d = decision_map.get(rel)
        if not d:
            continue
        dest_folder = _sanitize_folder_path(str(d.get("destination_folder_path") or "(root)"))
        src_folder = _folder_path_for_rel(rel)
        if dest_folder == src_folder:
            continue
        actions.append(
            Action(
                kind="move_file",
                folder_name=dest_folder,
                file_path=target / rel,
                file_name=Path(rel).name,
                details={"from": rel, "to_folder": dest_folder, "rationale": str(d.get("rationale") or "").strip()},
            )
        )

    # Index updates: any folder involved in create/move, plus parents of created folders.
    touched: set[str] = set()
    for f in create_unique:
        touched.add(f)
        if "/" in f:
            touched.add(f.rsplit("/", 1)[0])
    for a in actions:
        if a.kind == "move_file":
            to_folder = _sanitize_folder_path(str(a.folder_name or "(root)"))
            if to_folder != "(root)":
                touched.add(to_folder)
            from_rel = str((a.details or {}).get("from") or "")
            if from_rel:
                src_folder = _folder_path_for_rel(from_rel)
                if src_folder != "(root)":
                    touched.add(src_folder)

    # Compute planned layout for index content.
    planned_folder_to_files: dict[str, list[str]] = {}
    for rel in inventory_rel_set:
        planned_folder_to_files.setdefault(_folder_path_for_rel(rel), []).append(rel)
    for a in actions:
        if a.kind != "move_file":
            continue
        from_rel = str((a.details or {}).get("from") or "")
        if not from_rel:
            continue
        dest_folder = _sanitize_folder_path(str(a.folder_name or "(root)"))
        src_folder = _folder_path_for_rel(from_rel)
        if from_rel in planned_folder_to_files.get(src_folder, []):
            planned_folder_to_files[src_folder].remove(from_rel)
        new_rel = f"{dest_folder}/{Path(from_rel).name}" if dest_folder != "(root)" else Path(from_rel).name
        planned_folder_to_files.setdefault(dest_folder, []).append(new_rel)

    for folder_path in sorted({f for f in touched if f != "(root)"}, key=str.lower):
        rels = sorted(planned_folder_to_files.get(folder_path, []), key=str.lower)
        files_list: list[dict[str, str]] = []
        for fp in rels[:200]:
            prof = profiles.get(fp)
            summ = prof.summary if prof else ""
            files_list.append({"file_name": Path(fp).name, "summary": summ})
        desc = folder_desc.get(folder_path)
        managed_md = _render_managed_index(folder_path=folder_path, desc=desc, files=files_list)
        actions.append(Action(kind="update_index", folder_name=folder_path, index_markdown=managed_md, details={"managed": True}))

    # Add skip actions (for reporting/apply summary).
    for s in skipped:
        actions.append(
            Action(
                kind="skip_file",
                file_name=Path(str(s.get("file_path") or "")).name or None,
                file_path=_safe_join_under_target(target, str(s.get("file_path") or "")) if s.get("file_path") else None,
                details={"reason": s.get("reason")},
            )
        )

    report["actions"] = [asdict(a) for a in actions]
    if show_summaries:
        report["human_summary"] = _human_summary(moves=moves, created_folders=create_unique, skipped=skipped)

    if logging:
        _log(logging, "[exec] Create folders:")
        for f in create_unique:
            _log(logging, f"  - {f}")
        _log(logging, "[exec] Moves:")
        for a in actions:
            if a.kind == "move_file":
                _log(logging, f"  - {Path((a.details or {}).get('from') or '').name} -> {a.folder_name}/")
        if skipped:
            _log(logging, "[exec] Skipped:")
            for s in skipped:
                _log(logging, f"  - {s.get('file_path')} ({s.get('reason')})")

    return report


def apply_local_plan(*, target: Path, report: dict[str, Any], logging: bool) -> None:
    if not bool(report.get("accepted")):
        raise RuntimeError("Global plan is unaccepted; refusing to apply.")

    profiles = load_profiles(target)
    actions = report.get("actions") or []
    for a in actions:
        kind = a.get("kind")
        if kind == "create_folder":
            folder = _sanitize_folder_path(a.get("folder_name") or "")
            if folder == "(root)":
                continue
            p = _safe_join_under_target(target, folder)
            if not p.exists():
                _log(logging, f"[apply] Create folder: {folder}/")
                p.mkdir(parents=True, exist_ok=True)
        elif kind == "move_file":
            dest_folder = _sanitize_folder_path(a.get("folder_name") or "(root)")
            from_rel = str((a.get("details") or {}).get("from") or "").replace("\\", "/").lstrip("/")
            if not from_rel:
                continue
            src = _safe_join_under_target(target, from_rel)
            dest_dir = target if dest_folder == "(root)" else _safe_join_under_target(target, dest_folder)
            dest = dest_dir / src.name
            if not src.exists() or not src.is_file():
                continue
            if dest.exists():
                _log(logging, f"[apply] Skip move (dest exists): {src.name} -> {dest_folder}/")
                continue
            _log(logging, f"[apply] Move: {from_rel} -> {dest_folder}/")
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
            new_rel = _rel_posix(target, dest)
            move_profile_entry(profiles=profiles, old_rel_path=from_rel, new_rel_path=new_rel, new_abs_path=dest)
            mark_applied_destination(profiles=profiles, rel_path=new_rel, destination_folder=dest_folder)
        elif kind == "update_index":
            folder = _sanitize_folder_path(a.get("folder_name") or "")
            if folder == "(root)":
                continue
            idx = _safe_join_under_target(target, folder) / "_index.md"
            managed_md = str(a.get("index_markdown") or "")
            existing = idx.read_text(encoding="utf-8", errors="ignore") if idx.exists() else ""
            updated = managed_index_update(existing, managed_md)
            _log(logging, f"[apply] Update index: {folder}/_index.md (managed section)")
            idx.write_text(updated, encoding="utf-8")

    save_profiles(target, profiles)
