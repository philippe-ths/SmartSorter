from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Optional


@dataclass(frozen=True)
class FolderProfile:
    name: str
    desc: Optional[str]
    has_index: bool


@dataclass(frozen=True)
class FileProfile:
    file_name: str
    summary: str
    subject_label: str
    keywords: list[str]
    mime_type: Optional[str]
    text_chars: int


@dataclass(frozen=True)
class TargetFolder:
    name: str
    exists: bool


@dataclass(frozen=True)
class FilePlan:
    file_name: str
    target_folder: TargetFolder
    index_desc_if_new: Optional[str]
    rationale: str


CriticAction = Literal["keep", "use_existing_folder", "create_new_folder", "skip"]


@dataclass(frozen=True)
class Critique:
    file_name: str
    target_folder_name: str
    acceptable: bool
    critique_rationale: str
    suggested_action: Optional[CriticAction] = None
    suggested_folder_name: Optional[str] = None
    suggested_index_desc_if_new: Optional[str] = None
    suggested_rationale: Optional[str] = None


ActionKind = Literal["ensure_folder", "move_file", "update_index", "skip_file"]


@dataclass(frozen=True)
class Action:
    kind: ActionKind
    folder_name: Optional[str] = None
    file_path: Optional[Path] = None
    file_name: Optional[str] = None
    details: Optional[dict[str, Any]] = None
    index_markdown: Optional[str] = None
