from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional


@dataclass(frozen=True)
class DriveItem:
    id: str
    name: str
    mime_type: str
    modified_time: Optional[str] = None

    @property
    def is_folder(self) -> bool:
        return self.mime_type == "application/vnd.google-apps.folder"


@dataclass(frozen=True)
class FolderInfo:
    id: str
    name: str
    description: str = ""


@dataclass(frozen=True)
class FileProfile:
    file_id: str
    filename: str
    mime_type: str
    text_snippet: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Summary:
    summary: str
    keywords: list[str]
    subject_label: str


@dataclass(frozen=True)
class TargetFolder:
    name: str
    exists: bool


@dataclass(frozen=True)
class FolderDecision:
    target_folder: TargetFolder
    index_description_if_new: str
    rationale: str


@dataclass(frozen=True)
class PlanAction:
    kind: Literal["ensure_folder", "move_file", "write_index"]
    folder_name: str
    folder_id: Optional[str] = None
    file_id: Optional[str] = None
    file_name: Optional[str] = None
    file_path: Optional[str] = None
    index_markdown: Optional[str] = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class SortPlan:
    mode: Literal["drive", "local"]
    folder_id: Optional[str]
    local_path: Optional[str]
    actions: list[PlanAction]
    folder_name_to_id: dict[str, str] = field(default_factory=dict)
    report: list[dict[str, Any]] = field(default_factory=list)
