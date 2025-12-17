# SmartSorter (AI Folder Sorter) AI Instructions

## Big Picture Architecture
SmartSorter is an LLM-driven CLI tool for organizing local files into a shallow folder hierarchy (depth 1). It prioritizes safety and predictability over deep semantic taxonomy.

- **Core Flow**: `cli.py` -> `planner.py` (Scan -> Summarize -> Cluster -> Plan -> Critic -> Repair) -> `store.py` (Persist State) -> Apply.
- **State Management**: File summaries and metadata are cached in a local `.aifo/profiles.json` file to avoid re-processing unchanged files.
- **Decision Engine**: Purely LLM-based (Gemini). No heuristic fallbacks (regex/dates) are used for sorting logic.
- **Safety**: Read-only analysis by default. Write operations are strictly limited to: creating folders, moving files, and updating `_index.md`. **Never delete files or modify user content.**

## Critical Developer Workflows

### Running & Testing
- **Entry Point**: Run as a module: `python -m ai_folder_sorter ...`
- **Dry Run (Standard Dev Loop)**:
  ```bash
  python -m ai_folder_sorter --local-path /path/to/test --show-summaries --critic-iterations 1 --logging
  ```
- **Apply Changes**:
  ```bash
  python -m ai_folder_sorter --local-path /path/to/test --apply
  ```
- **Testing**: No formal test suite exists. Validate changes by running `python -m compileall ai_folder_sorter` and performing a dry-run on a sample folder.

### Environment
- Requires `GOOGLE_API_KEY` (Gemini) or Vertex AI ADC.
- Secrets (`.env`, `token.json`, `client_secret_*.json`) must be git-ignored.

## Project-Specific Patterns & Conventions

### 1. Bounded Context & Depth
- **Rule**: The tool *only* sees the target root and its immediate subfolders (Depth 1).
- **Implementation**: See `_list_bounded_inventory` in `planner.py`. Never traverse deeper recursively for sorting purposes.

### 2. The "Critic" Loop
- **Pattern**: Plans are not applied immediately. They pass through a "Critic" agent (see `adk_agents.py` and `planner.py`) to check for over-splitting or unstable folder names.
- **Repair**: If the critic rejects a plan, a "Repair" agent iterates on it.

### 3. Idempotent Index Updates
- **Pattern**: `_index.md` files describe folder contents.
- **Implementation**: Updates are restricted to a "Managed Index" section (see `_render_managed_index` in `planner.py`). User content outside this section is preserved.

### 4. Profile Store (`.aifo`)
- **Pattern**: `store.py` handles caching.
- **Key Logic**: `is_unchanged` checks file size + mtime. If changed, the file is re-summarized.

## Key Files
- `docs/functional_spec.md`: **Source of Truth** for behavior. Read this before changing logic.
- `ai_folder_sorter/planner.py`: Main orchestration logic.
- `ai_folder_sorter/adk_agents.py`: LLM prompts and interactions.
- `ai_folder_sorter/store.py`: Local state/cache management.
