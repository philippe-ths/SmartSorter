from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Optional, TypedDict


# =============================================================================
# TypedDict definitions for structured data passed between components
# =============================================================================

class FileProfileDict(TypedDict):
    """Structure for file profile data in planning context."""
    summary: str
    subject_label: str
    keywords: list[str]


class FilePlanningEntry(TypedDict):
    """A file entry in the planning snapshot."""
    file_path: str
    current_folder_path: str
    file_profile: FileProfileDict


class FolderContext(TypedDict):
    """Folder context in the planning snapshot."""
    folder_path: str
    name: str
    desc: Optional[str]
    has_index: bool


class ClusterInfo(TypedDict):
    """Cluster information for planning."""
    label: str
    size: int
    file_paths: list[str]


class PlanningRules(TypedDict):
    """Rules embedded in the planning snapshot."""
    no_deletions: bool
    no_renames: bool
    top_level_only: bool
    min_role_cluster_size: int
    min_project_cluster_size: int
    precedence: str


class PlanningSnapshot(TypedDict):
    """
    The complete context passed to the planner agent.
    
    This represents the "world state" the LLM uses to make decisions.
    """
    target: str
    rules: PlanningRules
    folders: list[FolderContext]
    files: list[FilePlanningEntry]
    role_clusters: list[ClusterInfo]
    project_clusters: list[ClusterInfo]


class CreateFolderAction(TypedDict):
    """Action to create a new folder."""
    kind: Literal["create_folder"]
    path: str
    index_desc: Optional[str]


class MoveFileAction(TypedDict):
    """Action to move a file."""
    kind: Literal["move_file"]
    from_: str  # Note: renamed from 'from' due to Python keyword
    to_folder: str
    rationale: str


class UpdateIndexAction(TypedDict):
    """Action to update a folder's index."""
    kind: Literal["update_index"]
    folder_path: str


class FileDecision(TypedDict, total=False):
    """A decision about where a file should go."""
    file_path: str
    current_folder_path: str  # Use "(root)" when currently in target root
    destination_folder_path: str  # Use "(root)" for no move
    destination_folder_exists: bool
    destination_folder_will_be_created: bool  # Derived from actions
    move_required: bool
    rationale: str


class GlobalPlan(TypedDict):
    """The output from the global planner."""
    actions: list[dict[str, Any]]  # Mix of CreateFolderAction, MoveFileAction, UpdateIndexAction
    file_decisions: list[FileDecision]


class CritiqueAdjustment(TypedDict, total=False):
    """A suggested adjustment from the critic."""
    kind: str
    action_index: int
    reason: str
    old_path: str
    new_path: str
    file_path: str
    new_destination_folder_path: str


class GlobalPlanCritique(TypedDict):
    """The output from the plan critic."""
    acceptable: bool
    critique_rationale: str
    suggested_adjustments: Optional[list[CritiqueAdjustment]]


class SkippedFileInfo(TypedDict, total=False):
    """Information about a skipped file."""
    file_path: str
    reason: str
    cached: bool
    chars: int


class PlanReport(TypedDict, total=False):
    """The final report from build_local_plan."""
    mode: str
    target: str
    store_dir: str
    models: dict[str, str]
    accepted: bool
    critique: Optional[GlobalPlanCritique]
    skipped: list[SkippedFileInfo]
    global_plan: GlobalPlan
    actions: list[dict[str, Any]]
    human_summary: str


# =============================================================================
# Dataclass definitions (existing)
# =============================================================================

@dataclass(frozen=True)
class FolderProfile:
    """Profile for an existing folder in the target."""
    folder_path: str  # target-relative folder path (POSIX), or "(root)" not used here
    name: str
    desc: Optional[str]
    has_index: bool


@dataclass(frozen=True)
class FileProfile:
    """Profile for a file's content and metadata."""
    file_name: str
    summary: str
    subject_label: str
    keywords: list[str]
    mime_type: Optional[str]
    text_chars: int


@dataclass(frozen=True)
class TargetFolder:
    """A folder that may or may not exist."""
    name: str
    exists: bool


@dataclass(frozen=True)
class FilePlan:
    """A plan for a single file."""
    file_name: str
    target_folder: TargetFolder
    index_desc_if_new: Optional[str]
    rationale: str


CriticAction = Literal["keep", "use_existing_folder", "create_new_folder", "skip"]


@dataclass(frozen=True)
class Critique:
    """Critique of a file plan."""
    file_name: str
    target_folder_name: str
    acceptable: bool
    critique_rationale: str
    suggested_action: Optional[CriticAction] = None
    suggested_folder_name: Optional[str] = None
    suggested_index_desc_if_new: Optional[str] = None
    suggested_rationale: Optional[str] = None


ActionKind = Literal["create_folder", "move_file", "update_index", "skip_file"]


@dataclass(frozen=True)
class Action:
    """An action to be applied to the filesystem."""
    kind: ActionKind
    folder_name: Optional[str] = None
    file_path: Optional[Path] = None
    file_name: Optional[str] = None
    details: Optional[dict[str, Any]] = None
    index_markdown: Optional[str] = None
