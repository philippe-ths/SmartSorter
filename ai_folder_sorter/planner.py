from __future__ import annotations

import mimetypes
import shutil
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from . import __version__
from .adk_agents import critique_plan_with_adk, decide_folder_with_adk, summarize_with_adk
from .drive import (
    download_text_like_file,
    ensure_folder,
    export_google_native_text,
    find_child_by_name,
    list_top_level_children,
    read_small_text_file,
    move_file,
    upsert_index_md,
)
from .models import FolderInfo, PlanAction, SortPlan
from .utils import extract_google_id_from_stub, is_bad_folder_name, normalize_folder_name, pick_fallback_folder


def _folder_descriptions(folder_id: str, *, supports_all_drives: bool) -> list[FolderInfo]:
    items = list_top_level_children(folder_id, supports_all_drives=supports_all_drives)
    folders = [i for i in items if i.is_folder]
    out: list[FolderInfo] = []
    for f in folders:
        idx = find_child_by_name(f.id, name="_index.md", supports_all_drives=supports_all_drives)
        desc = ""
        if idx:
            desc = read_small_text_file(idx.id, max_chars=20_000, supports_all_drives=supports_all_drives) or ""
        out.append(FolderInfo(id=f.id, name=f.name, description=desc))
    return out


def _extract_text_preview(file_id: str, *, mime_type: str, max_chars: int, supports_all_drives: bool) -> str:
    if mime_type.startswith("application/vnd.google-apps."):
        if mime_type == "application/vnd.google-apps.form":
            return ""
        exported = export_google_native_text(
            file_id, mime_type=mime_type, max_chars=max_chars, supports_all_drives=supports_all_drives
        )
        return exported or ""

    downloaded = download_text_like_file(
        file_id, mime_type=mime_type, max_chars=max_chars, supports_all_drives=supports_all_drives
    )
    return downloaded or ""


def _local_folder_descriptions(local_path: Path) -> list[FolderInfo]:
    out: list[FolderInfo] = []
    for p in sorted(local_path.iterdir(), key=lambda x: x.name.lower()):
        if not p.is_dir():
            continue
        desc = ""
        idx = p / "_index.md"
        if idx.exists() and idx.is_file():
            desc = idx.read_text(encoding="utf-8", errors="ignore")[:20_000]
        out.append(FolderInfo(id=str(p), name=p.name, description=desc))
    return out


def _local_read_text(path: Path, *, max_chars: int) -> str:
    if not path.exists() or not path.is_file():
        return ""
    try:
        with path.open("rb") as f:
            data = f.read(max_chars if max_chars and max_chars > 0 else 60_000)
        return data.decode("utf-8", errors="ignore")
    except Exception:
        return ""


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data and data.strip():
            self._parts.append(data.strip())

    def text(self) -> str:
        return "\n".join(self._parts)


def _local_read_html_text(path: Path, *, max_chars: int) -> str:
    raw = _local_read_text(path, max_chars=max_chars)
    if not raw:
        return ""
    parser = _HTMLTextExtractor()
    try:
        parser.feed(raw)
    except Exception:
        return ""
    return parser.text()


def _local_read_pdf_text(path: Path, *, max_chars: int) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError("Missing dependency: pypdf (required to extract PDF text).") from e

    try:
        reader = PdfReader(str(path))
        parts: list[str] = []
        for page in reader.pages:
            txt = page.extract_text() or ""
            if txt.strip():
                parts.append(txt)
            joined = "\n".join(parts)
            if max_chars and max_chars > 0 and len(joined) >= max_chars:
                return joined[:max_chars]
        return "\n".join(parts)[:max_chars] if max_chars and max_chars > 0 else "\n".join(parts)
    except Exception:
        return ""


def _local_preview_for_item(path: Path, *, max_chars: int, supports_all_drives: bool) -> tuple[str, str]:
    ext = path.suffix.lower()
    if ext in {".gdoc", ".gsheet", ".gslides", ".gform"}:
        file_id = extract_google_id_from_stub(path)
        if not file_id:
            return "", "application/vnd.google-apps.shortcut"
        if ext == ".gdoc":
            mime = "application/vnd.google-apps.document"
        elif ext == ".gsheet":
            mime = "application/vnd.google-apps.spreadsheet"
        elif ext == ".gslides":
            mime = "application/vnd.google-apps.presentation"
        else:
            mime = "application/vnd.google-apps.form"

        if mime == "application/vnd.google-apps.form":
            return "", mime

        text = export_google_native_text(
            file_id, mime_type=mime, max_chars=max_chars, supports_all_drives=supports_all_drives
        )
        return text or "", mime

    if ext in {".md", ".markdown"}:
        return _local_read_text(path, max_chars=max_chars), "text/markdown"

    guessed, _ = mimetypes.guess_type(path.name)
    mime = guessed or "application/octet-stream"
    if ext == ".pdf":
        return _local_read_pdf_text(path, max_chars=max_chars), "application/pdf"
    if ext in {".html", ".htm"}:
        return _local_read_html_text(path, max_chars=max_chars), mime
    if mime.startswith("text/") or mime in {"application/json", "application/xml"}:
        return _local_read_text(path, max_chars=max_chars), mime
    return "", mime


def build_plan(
    *,
    folder_id: str | None,
    local_path: str | None,
    max_chars: int,
    supports_all_drives: bool,
    model_summary: str,
    model_folder: str,
    model_critic: str,
    critic_iterations: int,
    adk_timeout_seconds: int,
    emit_report: bool,
) -> SortPlan:
    # This project requires ADK + an LLM-backed summarizer/critic.
    # (Per requirements: no heuristic fallback mode.)
    if folder_id:
        return _build_drive_plan(
            folder_id=folder_id,
            max_chars=max_chars,
            supports_all_drives=supports_all_drives,
            model_summary=model_summary,
            model_folder=model_folder,
            model_critic=model_critic,
            critic_iterations=critic_iterations,
            adk_timeout_seconds=adk_timeout_seconds,
            emit_report=emit_report,
        )

    if not local_path:
        raise ValueError("Either folder_id or local_path is required.")
    return _build_local_plan(
        local_path=local_path,
        max_chars=max_chars,
        supports_all_drives=supports_all_drives,
        model_summary=model_summary,
        model_folder=model_folder,
        model_critic=model_critic,
        critic_iterations=critic_iterations,
        adk_timeout_seconds=adk_timeout_seconds,
        emit_report=emit_report,
    )


def _build_drive_plan(
    *,
    folder_id: str,
    max_chars: int,
    supports_all_drives: bool,
    model_summary: str,
    model_folder: str,
    model_critic: str,
    critic_iterations: int,
    adk_timeout_seconds: int,
    emit_report: bool,
) -> SortPlan:
    items = list_top_level_children(folder_id, supports_all_drives=supports_all_drives)
    folders = _folder_descriptions(folder_id, supports_all_drives=supports_all_drives)
    folder_names = sorted({f.name for f in folders})
    fallback = pick_fallback_folder(folder_names)

    existing_folders_payload = [
        {"name": f.name, "description": (f.description or "").strip()} for f in sorted(folders, key=lambda x: x.name)
    ]

    file_entries: list[dict[str, Any]] = []
    report: list[dict[str, Any]] = []
    report_by_key: dict[str, dict[str, Any]] = {}

    for item in items:
        if item.is_folder:
            continue

        text_snippet = _extract_text_preview(
            item.id, mime_type=item.mime_type, max_chars=max_chars, supports_all_drives=supports_all_drives
        )
        file_profile: dict[str, Any] = {
            "filename": item.name,
            "mimeType": item.mime_type,
            "textSnippet": text_snippet,
            "metadata": {"modifiedTime": item.modified_time},
        }

        if not text_snippet.strip():
            raise RuntimeError(f"No extractable text for Drive file: {item.name} ({item.mime_type}).")
        summary_obj = summarize_with_adk(
            model=model_summary,
            filename=item.name,
            mime_type=item.mime_type,
            text_snippet=text_snippet,
            metadata={"modifiedTime": item.modified_time},
            timeout_seconds=adk_timeout_seconds,
        )
        if not summary_obj:
            raise RuntimeError(f"Failed to summarize Drive file: {item.name}")
        file_profile["summary"] = summary_obj.summary
        file_profile["keywords"] = summary_obj.keywords
        file_profile["subject_label"] = summary_obj.subject_label

        decision_obj = decide_folder_with_adk(
            model=model_folder,
            file_profile=file_profile,
            existing_folders=existing_folders_payload,
            timeout_seconds=adk_timeout_seconds,
        )
        if not decision_obj:
            raise RuntimeError(f"Failed to decide folder for Drive file: {item.name}")
        candidate = normalize_folder_name(decision_obj.target_folder.name)
        if is_bad_folder_name(candidate):
            raise RuntimeError(f"LLM proposed an invalid folder name: {candidate!r} for file {item.name!r}")
        target_folder_name = candidate
        index_desc_if_new = decision_obj.index_description_if_new or ""
        rationale = decision_obj.rationale or ""
        if emit_report:
            rep: dict[str, Any] = {
                "file_key": item.id,
                "filename": item.name,
                "mimeType": item.mime_type,
                "textChars": len(text_snippet),
                "summary": {
                    "summary": summary_obj.summary,
                    "keywords": summary_obj.keywords,
                    "subject_label": summary_obj.subject_label,
                },
                "decision_initial": {
                    "target_folder": {"name": target_folder_name, "exists": decision_obj.target_folder.exists},
                    "index_description_if_new": decision_obj.index_description_if_new,
                    "rationale": decision_obj.rationale,
                },
            }
            report.append(rep)
            report_by_key[item.id] = rep

        file_entries.append(
            {
                "file_key": item.id,
                "filename": item.name,
                "mimeType": item.mime_type,
                "textChars": len(text_snippet),
                "summary": {
                    "summary": summary_obj.summary,
                    "keywords": summary_obj.keywords,
                    "subject_label": summary_obj.subject_label,
                },
                "proposed": {
                    "target_folder": {"name": target_folder_name, "exists": target_folder_name in folder_names},
                    "index_description_if_new": index_desc_if_new,
                    "rationale": rationale,
                },
            }
        )

    if critic_iterations > 0:
        file_entries, critic_notes = _apply_critic_loop(
            file_entries=file_entries,
            existing_folders=existing_folders_payload,
            folder_names=folder_names,
            model_critic=model_critic,
            critic_iterations=critic_iterations,
            timeout_seconds=adk_timeout_seconds,
        )
        if emit_report:
            for e in file_entries:
                rep = report_by_key.get(e["file_key"])
                if not rep:
                    continue
                initial = rep.get("decision_initial", {})
                initial_tf = initial.get("target_folder", {}) if isinstance(initial, dict) else {}
                initial_name = (initial_tf.get("name") or "").strip()
                initial_index_desc = (initial.get("index_description_if_new") or "").strip() if isinstance(initial, dict) else ""
                initial_rationale = (initial.get("rationale") or "").strip() if isinstance(initial, dict) else ""
                final_tf = e["proposed"]["target_folder"]
                final_name = final_tf.get("name") or ""
                final_index_desc = (e["proposed"].get("index_description_if_new") or "").strip()
                final_rationale = (e["proposed"].get("rationale") or "").strip()
                rep["decision_final"] = {
                    "target_folder": {"name": final_name, "exists": bool(final_tf.get("exists"))},
                    "index_description_if_new": final_index_desc,
                    "rationale": final_rationale,
                }
                changes: dict[str, Any] = {}
                if final_name != initial_name:
                    changes["target_folder"] = {"from": initial_name, "to": final_name}
                if final_index_desc != initial_index_desc:
                    changes["index_description_if_new"] = {"from": initial_index_desc, "to": final_index_desc}
                if final_rationale != initial_rationale:
                    changes["rationale"] = {"from": initial_rationale, "to": final_rationale}
                rep["critic_changed"] = bool(changes)
                if changes:
                    rep["critic_change"] = changes
        if emit_report:
            report.append({"critic": critic_notes})
    elif emit_report:
        for e in file_entries:
            rep = report_by_key.get(e["file_key"])
            if not rep:
                continue
            tf = e["proposed"]["target_folder"]
            rep["decision_final"] = {
                "target_folder": {"name": tf.get("name") or "", "exists": bool(tf.get("exists"))},
                "index_description_if_new": e["proposed"].get("index_description_if_new", ""),
                "rationale": e["proposed"].get("rationale", ""),
            }
            rep["critic_changed"] = False

    actions, touched_folder_names, intended_index_desc = _actions_from_entries(
        mode="drive",
        base_folder_id=folder_id,
        folder_names=folder_names,
        entries=file_entries,
    )

    for name in sorted(touched_folder_names):
        desc = intended_index_desc.get(name) or f"Files related to {name}."
        md = _render_index_md(folder_name=name, description=desc)
        actions.append(PlanAction(kind="write_index", folder_name=name, index_markdown=md))

    return SortPlan(
        mode="drive", folder_id=folder_id, local_path=None, actions=actions, folder_name_to_id={}, report=report
    )


def _build_local_plan(
    *,
    local_path: str,
    max_chars: int,
    supports_all_drives: bool,
    model_summary: str,
    model_folder: str,
    model_critic: str,
    critic_iterations: int,
    adk_timeout_seconds: int,
    emit_report: bool,
) -> SortPlan:
    base = Path(local_path).expanduser().resolve()
    if not base.exists() or not base.is_dir():
        raise ValueError(f"Not a folder: {base}")

    folders = _local_folder_descriptions(base)
    folder_names = sorted({f.name for f in folders})
    fallback = pick_fallback_folder(folder_names)
    existing_folders_payload = [
        {"name": f.name, "description": (f.description or "").strip()} for f in sorted(folders, key=lambda x: x.name)
    ]

    file_entries: list[dict[str, Any]] = []
    report: list[dict[str, Any]] = []
    report_by_key: dict[str, dict[str, Any]] = {}

    for p in sorted(base.iterdir(), key=lambda x: x.name.lower()):
        if p.is_dir():
            continue
        if p.name == "_index.md":
            continue

        text_snippet, mime_type = _local_preview_for_item(
            p, max_chars=max_chars, supports_all_drives=supports_all_drives
        )
        file_profile: dict[str, Any] = {
            "filename": p.name,
            "mimeType": mime_type,
            "textSnippet": text_snippet,
            "metadata": {"local_path": str(p)},
        }

        if not text_snippet.strip():
            raise RuntimeError(f"No extractable text for local file: {p.name} ({mime_type}).")
        try:
            summary_obj = summarize_with_adk(
                model=model_summary,
                filename=p.name,
                mime_type=mime_type,
                text_snippet=text_snippet,
                metadata={"local_path": str(p)},
                timeout_seconds=adk_timeout_seconds,
            )
        except Exception as e:
            raise RuntimeError(f"ADK summarization failed for local file: {p.name}") from e
        if not summary_obj:
            raise RuntimeError(f"Failed to summarize local file: {p.name}")
        file_profile["summary"] = summary_obj.summary
        file_profile["keywords"] = summary_obj.keywords
        file_profile["subject_label"] = summary_obj.subject_label

        try:
            decision_obj = decide_folder_with_adk(
                model=model_folder,
                file_profile=file_profile,
                existing_folders=existing_folders_payload,
                timeout_seconds=adk_timeout_seconds,
            )
        except Exception as e:
            raise RuntimeError(f"ADK folder decision failed for local file: {p.name}") from e
        if not decision_obj:
            raise RuntimeError(f"Failed to decide folder for local file: {p.name}")
        candidate = normalize_folder_name(decision_obj.target_folder.name)
        if is_bad_folder_name(candidate):
            raise RuntimeError(f"LLM proposed an invalid folder name: {candidate!r} for file {p.name!r}")
        target_folder_name = candidate
        index_desc_if_new = decision_obj.index_description_if_new or ""
        rationale = decision_obj.rationale or ""
        if emit_report:
            rep: dict[str, Any] = {
                "file_key": str(p),
                "filename": p.name,
                "mimeType": mime_type,
                "textChars": len(text_snippet),
                "summary": {
                    "summary": summary_obj.summary,
                    "keywords": summary_obj.keywords,
                    "subject_label": summary_obj.subject_label,
                },
                "decision_initial": {
                    "target_folder": {"name": target_folder_name, "exists": decision_obj.target_folder.exists},
                    "index_description_if_new": decision_obj.index_description_if_new,
                    "rationale": decision_obj.rationale,
                },
            }
            report.append(rep)
            report_by_key[str(p)] = rep
        file_entries.append(
            {
                "file_key": str(p),
                "filename": p.name,
                "file_path": str(p),
                "mimeType": mime_type,
                "textChars": len(text_snippet),
                "summary": {
                    "summary": summary_obj.summary,
                    "keywords": summary_obj.keywords,
                    "subject_label": summary_obj.subject_label,
                },
                "proposed": {
                    "target_folder": {"name": target_folder_name, "exists": target_folder_name in folder_names},
                    "index_description_if_new": index_desc_if_new,
                    "rationale": rationale,
                },
            }
        )

    if critic_iterations > 0:
        file_entries, critic_notes = _apply_critic_loop(
            file_entries=file_entries,
            existing_folders=existing_folders_payload,
            folder_names=folder_names,
            model_critic=model_critic,
            critic_iterations=critic_iterations,
            timeout_seconds=adk_timeout_seconds,
        )
        if emit_report:
            for e in file_entries:
                rep = report_by_key.get(e["file_key"])
                if not rep:
                    continue
                initial = rep.get("decision_initial", {})
                initial_tf = initial.get("target_folder", {}) if isinstance(initial, dict) else {}
                initial_name = (initial_tf.get("name") or "").strip()
                initial_index_desc = (initial.get("index_description_if_new") or "").strip() if isinstance(initial, dict) else ""
                initial_rationale = (initial.get("rationale") or "").strip() if isinstance(initial, dict) else ""
                final_tf = e["proposed"]["target_folder"]
                final_name = final_tf.get("name") or ""
                final_index_desc = (e["proposed"].get("index_description_if_new") or "").strip()
                final_rationale = (e["proposed"].get("rationale") or "").strip()
                rep["decision_final"] = {
                    "target_folder": {"name": final_name, "exists": bool(final_tf.get("exists"))},
                    "index_description_if_new": final_index_desc,
                    "rationale": final_rationale,
                }
                changes: dict[str, Any] = {}
                if final_name != initial_name:
                    changes["target_folder"] = {"from": initial_name, "to": final_name}
                if final_index_desc != initial_index_desc:
                    changes["index_description_if_new"] = {"from": initial_index_desc, "to": final_index_desc}
                if final_rationale != initial_rationale:
                    changes["rationale"] = {"from": initial_rationale, "to": final_rationale}
                rep["critic_changed"] = bool(changes)
                if changes:
                    rep["critic_change"] = changes
        if emit_report:
            report.append({"critic": critic_notes})
    elif emit_report:
        for e in file_entries:
            rep = report_by_key.get(e["file_key"])
            if not rep:
                continue
            tf = e["proposed"]["target_folder"]
            rep["decision_final"] = {
                "target_folder": {"name": tf.get("name") or "", "exists": bool(tf.get("exists"))},
                "index_description_if_new": e["proposed"].get("index_description_if_new", ""),
                "rationale": e["proposed"].get("rationale", ""),
            }
            rep["critic_changed"] = False

    actions, touched_folder_names, intended_index_desc = _actions_from_entries(
        mode="local",
        base_folder_id=None,
        folder_names=folder_names,
        entries=file_entries,
    )

    for name in sorted(touched_folder_names):
        desc = intended_index_desc.get(name) or f"Files related to {name}."
        md = _render_index_md(folder_name=name, description=desc)
        actions.append(PlanAction(kind="write_index", folder_name=name, index_markdown=md))

    return SortPlan(
        mode="local", folder_id=None, local_path=str(base), actions=actions, folder_name_to_id={}, report=report
    )


def _apply_critic_loop(
    *,
    file_entries: list[dict[str, Any]],
    existing_folders: list[dict[str, str]],
    folder_names: list[str],
    model_critic: str,
    critic_iterations: int,
    timeout_seconds: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_key = {e["file_key"]: e for e in file_entries}
    notes: dict[str, Any] = {"iterations": []}

    for i in range(max(0, critic_iterations)):
        draft_plan = {
            "existing_folders": existing_folders,
            "proposed_assignments": [
                {
                    "file_key": e["file_key"],
                    "filename": e["filename"],
                    "summary": e.get("summary", {}),
                    "target_folder": e["proposed"]["target_folder"],
                    "rationale": e["proposed"].get("rationale", ""),
                }
                for e in file_entries
            ],
        }
        critique = critique_plan_with_adk(model=model_critic, draft_plan=draft_plan, timeout_seconds=timeout_seconds)
        if not critique:
            raise RuntimeError("Critic agent returned invalid output.")
        notes["iterations"].append(critique)
        if critique.get("approved") is True:
            return file_entries, notes

        revised = critique.get("revised_assignments")
        if not isinstance(revised, list) or not revised:
            raise RuntimeError("Critic did not approve but provided no revisions.")

        for r in revised:
            if not isinstance(r, dict):
                continue
            file_key = r.get("file_key")
            if file_key not in by_key:
                continue
            tf = r.get("target_folder") if isinstance(r.get("target_folder"), dict) else {}
            name = normalize_folder_name((tf.get("name") or "").strip())
            if not name or is_bad_folder_name(name):
                raise RuntimeError(f"Critic proposed an invalid folder name: {name!r}")
            by_key[file_key]["proposed"]["target_folder"] = {"name": name, "exists": name in folder_names}
            by_key[file_key]["proposed"]["index_description_if_new"] = (r.get("index_description_if_new") or "").strip()
            by_key[file_key]["proposed"]["rationale"] = (r.get("rationale") or "").strip()

        file_entries = list(by_key.values())

    raise RuntimeError("Critic loop reached max iterations without approval.")


def _actions_from_entries(
    *,
    mode: str,
    base_folder_id: str | None,
    folder_names: list[str],
    entries: list[dict[str, Any]],
) -> tuple[list[PlanAction], set[str], dict[str, str]]:
    actions: list[PlanAction] = []
    ensured_names: set[str] = set()
    touched: set[str] = set()
    intended_index_desc: dict[str, str] = {}

    for e in entries:
        target_name = e["proposed"]["target_folder"]["name"]
        index_desc = (e["proposed"].get("index_description_if_new") or "").strip()
        rationale = (e["proposed"].get("rationale") or "").strip()

        if target_name not in folder_names and target_name not in ensured_names:
            actions.append(
                PlanAction(
                    kind="ensure_folder",
                    folder_name=target_name,
                    details={"reason": "Create folder (if missing)."},
                )
            )
            ensured_names.add(target_name)
            if index_desc:
                intended_index_desc[target_name] = index_desc
            touched.add(target_name)

        if mode == "drive":
            actions.append(
                PlanAction(
                    kind="move_file",
                    folder_name=target_name,
                    file_id=e["file_key"],
                    file_name=e["filename"],
                    details={"rationale": rationale},
                )
            )
        else:
            actions.append(
                PlanAction(
                    kind="move_file",
                    folder_name=target_name,
                    file_name=e["filename"],
                    file_path=e.get("file_path"),
                    details={"rationale": rationale},
                )
            )
        touched.add(target_name)

    return actions, touched, intended_index_desc


def _render_index_md(*, folder_name: str, description: str) -> str:
    now = datetime.utcnow().strftime("%Y-%m-%d")
    description = (description or "").strip()
    return (
        f"# {folder_name}\n\n"
        f"{description}\n\n"
        f"---\n"
        f"_Generated by SmartSorter {__version__} on {now}._\n"
    )


def execute_plan(plan: SortPlan, *, supports_all_drives: bool) -> None:
    target = plan.folder_id if plan.mode == "drive" else plan.local_path
    print(f"Target folder: {target}")
    print(f"Planned actions: {len(plan.actions)}")
    if plan.mode == "local":
        _execute_local_plan(plan)
        return
    confirm = input("Apply these changes to Google Drive? Type 'yes' to continue: ").strip().lower()
    if confirm != "yes":
        print("Cancelled.")
        return

    folder_name_to_id: dict[str, str] = {}

    # First ensure folders and collect IDs.
    for a in plan.actions:
        if a.kind != "ensure_folder":
            continue
        folder_id = ensure_folder(plan.folder_id, name=a.folder_name, supports_all_drives=supports_all_drives)
        folder_name_to_id[a.folder_name] = folder_id

    # Execute moves
    for a in plan.actions:
        if a.kind != "move_file":
            continue
        to_id = folder_name_to_id.get(a.folder_name) or ensure_folder(
            plan.folder_id, name=a.folder_name, supports_all_drives=supports_all_drives
        )
        folder_name_to_id[a.folder_name] = to_id
        print(f"Move: {a.file_name} -> {a.folder_name}")
        move_file(
            a.file_id or "",
            from_parent_id=plan.folder_id,
            to_parent_id=to_id,
            supports_all_drives=supports_all_drives,
        )

    # Write indexes
    for a in plan.actions:
        if a.kind != "write_index":
            continue
        folder_id = folder_name_to_id.get(a.folder_name) or ensure_folder(
            plan.folder_id, name=a.folder_name, supports_all_drives=supports_all_drives
        )
        folder_name_to_id[a.folder_name] = folder_id
        print(f"Index: {a.folder_name}/_index.md")
        upsert_index_md(folder_id, index_markdown=a.index_markdown or "", supports_all_drives=supports_all_drives)


def _execute_local_plan(plan: SortPlan) -> None:
    if not plan.local_path:
        raise ValueError("local_path missing for local plan")
    base = Path(plan.local_path)
    confirm = input("Apply these changes to local filesystem? Type 'yes' to continue: ").strip().lower()
    if confirm != "yes":
        print("Cancelled.")
        return

    # Ensure folders
    for a in plan.actions:
        if a.kind != "ensure_folder":
            continue
        (base / a.folder_name).mkdir(parents=True, exist_ok=True)

    # Moves
    for a in plan.actions:
        if a.kind != "move_file":
            continue
        if not a.file_path:
            continue
        src = Path(a.file_path)
        dest_dir = base / a.folder_name
        dest = dest_dir / src.name
        if src.resolve() == dest.resolve():
            continue
        print(f"Move: {src.name} -> {a.folder_name}")
        shutil.move(str(src), str(dest))

    # Indexes
    for a in plan.actions:
        if a.kind != "write_index":
            continue
        idx = base / a.folder_name / "_index.md"
        print(f"Index: {a.folder_name}/_index.md")
        idx.write_text(a.index_markdown or "", encoding="utf-8")
