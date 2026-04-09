"""
LLM prompt templates for SmartSorter.

This module centralizes all prompt/instruction strings used in LLM calls.
Separating prompts from agent code makes it easier to iterate on prompt
engineering without touching function signatures or control flow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Prompt:
    """
    A structured prompt template.
    
    Attributes:
        name: Identifier for the prompt (for logging/debugging)
        instruction: The system instruction for the LLM
        version: Optional version string for tracking prompt iterations
    """
    name: str
    instruction: str
    version: Optional[str] = None


# =============================================================================
# File Summarization Prompt
# =============================================================================

SUMMARIZE_FILE = Prompt(
    name="summarize_file",
    version="1.0.0",
    instruction="""
You summarise a file into a strict JSON object with keys:
- summary: string, max 200 characters
- subject_label: string, max 50 characters
- keywords: array of 5 to 8 short words/phrases

Rules:
- Base the result ONLY on the provided extracted text. Do not guess from file name, path, or metadata.
- Keep it concise and factual.
- Return JSON only.
""".strip(),
)


# =============================================================================
# Global Planning Prompt
# =============================================================================

PLAN_GLOBAL = Prompt(
    name="plan_global",
    version="1.1.0",
    instruction="""
You generate a single GLOBAL filing plan for a target folder.

Goal:
- Produce predictable, balanced, and low-surprise placements.
- Use a two-tier folder taxonomy:
  1. Project/Topic folders (specific): Use for mini-collections (2+ files) that clearly belong together.
  2. Role folders (general): Use for broad, recurring categories (e.g., Risk Assessments, Activity Plans) that act as "shock absorbers".
- Precedence: Project/Topic folder wins over Role folder. If a file belongs to a project mini-collection, put it there even if it also fits a role.

Rules:
- Do NOT delete anything.
- Do NOT rename existing folders.
- Do NOT modify file contents.
- Do NOT guess from filenames or timestamps; use only the provided planning snapshot (stored profiles and folder context).
- Avoid 1-file folders. Only create a new folder if it will contain 2+ files (mini-collection) or if it's a strong recurring role.
- Folder names must be plain-language, stable categories (prefer plural nouns).
- Avoid entity-based names (people/companies), time-based names (years/quarters), and filetype buckets (PDFs, Images).
- Produce a placement decision for EVERY file with a profile, even if it is "leave in root".

Return strict JSON ONLY with this schema:

actions[] (ordered):
- {"kind": "create_folder", "path": "Folder/Subfolder", "index_desc": "..." | null}
- {"kind": "move_file", "from": "rel/path/to/file.ext", "to_folder": "Folder/Subfolder" | "(root)", "rationale": "..."}
- {"kind": "update_index", "folder_path": "Folder/Subfolder"}

file_decisions[] (one entry per file with a profile):
- file_path: relative path to file
- current_folder_path: use "(root)" when currently in target root
- destination_folder_path: use "(root)" for no move
- destination_folder_exists: true if folder already exists
- destination_folder_will_be_created: true if folder is in create_folder actions
- move_required: true if current_folder_path != destination_folder_path
- rationale: one line explanation

Example:
{
  "actions": [
    {"kind": "create_folder", "path": "Camp Gadgets", "index_desc": "Camp Gadgets activity files and related risk assessments"},
    {"kind": "move_file", "from": "RA - Camp Gadgets.docx", "to_folder": "Camp Gadgets", "rationale": "Paired plan + RA mini-collection"},
    {"kind": "update_index", "folder_path": "Camp Gadgets"}
  ],
  "file_decisions": [
    {"file_path": "RA - Camp Gadgets.docx", "current_folder_path": "(root)", "destination_folder_path": "Camp Gadgets", "destination_folder_exists": false, "destination_folder_will_be_created": true, "move_required": true, "rationale": "Paired plan + RA mini-collection"},
    {"file_path": "random-note.md", "current_folder_path": "(root)", "destination_folder_path": "(root)", "destination_folder_exists": true, "destination_folder_will_be_created": false, "move_required": false, "rationale": "No recurring cluster; avoid one-off folder"}
  ]
}
""".strip(),
)


# =============================================================================
# Global Plan Critique Prompt
# =============================================================================

CRITIQUE_GLOBAL_PLAN = Prompt(
    name="critique_global_plan",
    version="1.0.0",
    instruction="""
You are a critic that checks whether a GLOBAL filing plan is acceptable and follows the "Balanced Specificity" taxonomy.

Acceptance guidance:
- Approve when the plan matches what a reasonable human would expect and avoids churn.
- Reject when:
  - the plan creates 1-file folders (hard bias against one-offs),
  - the plan creates vague or misleading folders (e.g., "Admin", "Documents", "Misc"),
  - the plan violates precedence (e.g., a file that belongs in a project mini-collection is put in a general role folder instead),
  - the plan over-splits (too many new folders in one run),
  - folder names are entity-based, time-based, or filetype-based.

Return strict JSON ONLY:
{
  "acceptable": true|false,
  "critique_rationale": "...",
  "suggested_adjustments": [
    {"kind": "remove_action", "action_index": 0, "reason": "..."},
    {"kind": "rename_new_folder", "old_path": "A/B", "new_path": "A/C", "reason": "..."},
    {"kind": "change_destination", "file_path": "rel/path.ext", "new_destination_folder_path": "(root)" | "X/Y", "reason": "..."}
  ] | null
}
""".strip(),
)


# =============================================================================
# Global Plan Repair Prompt
# =============================================================================

REPAIR_GLOBAL_PLAN = Prompt(
    name="repair_global_plan",
    version="1.0.0",
    instruction="""
You repair a GLOBAL filing plan using critic feedback.

Inputs:
- planning_snapshot (context)
- plan (original plan)
- critique (critic feedback with suggested_adjustments)

Output:
- Return a revised plan with the exact same schema as the original plan:
{
  "actions": [...],
  "file_decisions": [...]
}

Rules:
- Apply critic guidance where reasonable.
- Keep changes minimal while making the plan acceptable and low-surprise.
- Return JSON only.
""".strip(),
)


# =============================================================================
# Prompt Registry (for future version management)
# =============================================================================

class PromptRegistry:
    """
    Registry for managing prompt versions.
    
    This provides a central lookup for prompts and can be extended to support
    A/B testing, prompt versioning, or loading prompts from external sources.
    """
    
    def __init__(self) -> None:
        self._prompts: dict[str, Prompt] = {}
        self._register_defaults()
    
    def _register_defaults(self) -> None:
        """Register all default prompts."""
        for prompt in [SUMMARIZE_FILE, PLAN_GLOBAL, CRITIQUE_GLOBAL_PLAN, REPAIR_GLOBAL_PLAN]:
            self._prompts[prompt.name] = prompt
    
    def get(self, name: str) -> Prompt:
        """
        Get a prompt by name.
        
        Args:
            name: The prompt name
            
        Returns:
            The prompt
            
        Raises:
            KeyError: If the prompt is not found
        """
        if name not in self._prompts:
            raise KeyError(f"Prompt not found: {name}")
        return self._prompts[name]
    
    def register(self, prompt: Prompt) -> None:
        """
        Register or override a prompt.
        
        Args:
            prompt: The prompt to register
        """
        self._prompts[prompt.name] = prompt
    
    def list_prompts(self) -> list[str]:
        """Return a list of registered prompt names."""
        return list(self._prompts.keys())


# Global registry instance
_registry = PromptRegistry()


def get_prompt(name: str) -> Prompt:
    """Get a prompt from the global registry."""
    return _registry.get(name)


def register_prompt(prompt: Prompt) -> None:
    """Register a prompt in the global registry."""
    _registry.register(prompt)
