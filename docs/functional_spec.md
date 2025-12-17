# SmartSorter / AI Folder Sorter — Functional Specification

This spec describes the intended end-to-end workflow. If CLI UX or workflow ordering ever diverges, treat it as a bug unless intentionally re-scoped in `docs/plan.md`.

## 1) Purpose

SmartSorter is a CLI tool that organises files inside a user-chosen **local** target folder by:

- extracting bounded text previews from files,
- producing and storing a structured `file_profile` for each file,
- generating a **global plan** that can both place files and refactor folders (splits) when strong subtopic clusters emerge,
- running a **global** critic/repair loop to reduce surprise and prevent over-splitting,
- producing an execution plan and (optionally) applying it (create folders, move files, update `_index.md`).

The system is intentionally LLM-driven: it does not provide a non-LLM heuristic fallback.

## 2) Design Goals

- **Predictable filing**: pick the folder a “reasonable human would expect”.
- **Low-surprise moves**: avoid narrow, time-based, or entity-based folder creation.
- **Stable folder set**: prefer reusing existing folders; create new folders only when justified.
- **Useful refactors**: split folders only when strong recurring subtopic clusters exist.
- **Safety-scoped changes**: only create folders, move files, and write/update `_index.md`.
- **Explainability**: provide short rationales and clear logs when enabled.

## 3) Non-Goals

- Deep semantic taxonomy or maximum topical precision.
- Traversing deeper than one folder level below the target.
- Renaming existing folders, deleting files/folders, or modifying user file contents.
- Guessing based on filename/metadata when content extraction fails.
- Google Drive API integrations in the default local flow (treat synced Drive folders as normal local storage).

## 4) Operating Modes

### 4.1 Local Folder Mode (primary)

- User provides a local filesystem path (the “target folder”).
- The tool only operates within:
  - the target folder root, and
  - its **direct subfolders** (depth 1).
- No traversal beyond depth 1.

## 5) User Experience (CLI)

### 5.1 Core commands

- Dry-run (default): builds a plan and prints what it would do.
- Apply mode: requires `--apply` and a single confirmation prompt.

### 5.2 Expected CLI flags (behavioral contract)

The following flags define the intended UX/behavior:

- `--local-path <path>`: target folder on local filesystem.
- `--apply`: apply the accepted plan (prompts first).
- `--max-chars <n>`: cap extracted preview text (default: 60000).
- `--min-chars <n>`: minimum extracted text to profile a file (default: 500).
- `--critic-iterations <n>`: max critic/repair iterations for global plan review (default: 1–2).
- `--min-cluster-size <n>`: minimum cluster size to qualify as a “strong” subtopic cluster (default: 0 = auto-dynamic based on file count).
- `--show-summaries`: print human-readable summaries from stored profiles / plan decisions.
- `--logging`: emit structured log-style lines.

## 6) End-to-End Workflow (Local)

### Step 1 — Select target folder

**Input**: `--local-path`.

**Rules**:
- The target must be an existing directory.
- The tool’s action scope is limited to the target root and its direct subfolders.

**Logging** (when `--logging`):

```text
[init] Target: /abs/path/to/target
[init] Models: summariser=gemini-2.0-flash-lite, planner=gemini-2.0-flash-lite, critic=gemini-2.0-flash-lite
[init] Mode: dry-run (apply=false)
```

### Step 2 — Inventory scan (bounded depth)

**Action**:
- List files in:
  - the target folder root, and
  - each direct subfolder (depth 1).
- Do not traverse deeper.

**Logging**:

```text
[scan] Root files to consider (12):
  - file1.pdf
  - file2.txt
[scan] Direct subfolders (5):
  - Scouts
  - Finance
[scan] Depth-1 files to consider (88)
```

### Step 3 — Build folder context

For each direct subfolder:
- Read `_index.md` if present.
- Build a `folder_profile` from folder name + short description from `_index.md`.

**Logging**:

```text
[context] Folder profiles (5):
  - Scouts (index: yes) desc: scouts admin, activities, plans
  - Finance (index: yes) desc: invoices, tax, banking
```

### Step 4 — Build or refresh file profiles (store-first)

#### 4.1 Profile store

- Maintain a local store of file intelligence (for example under `.aifo/` in the target folder).
- For each file in the inventory:
  - if a stored profile exists and the file is unchanged (mtime/size), reuse it,
  - otherwise extract and summarise, then upsert the profile.

**Logging**:

```text
[store] Loaded profiles: 83
[store] Needs summarise: 17
```

#### 4.2 Extract content (bounded, no fallback)

**Action**:
- Extract text using an extractor determined by extension/MIME sniffing.
- Cap extraction at `--max-chars`.

**Skip rule**:
- If usable extracted text is below `--min-chars`, skip profiling the file.
- Do not fall back to filename, path, timestamps, or other metadata.

**Logging**:

```text
[extract] Scouts/risk_assessment_01.pdf method=pdf-text chars=43120 (truncated=false)
[extract] scan.png method=image chars=0
[skip] scan.png reason="insufficient extracted text" chars=0 min=500
```

#### 4.3 Summarise (Summariser Agent)

**Output**: `file_profile` JSON:
- `summary` (max 200 characters)
- `subject_label` (max 50 characters)
- `keywords` (5–8)

Store the resulting profile for future planning.

**Logging**:

```text
[summarise] risk_assessment_01.pdf summary="Risk assessment for Scouts hike activity, hazards and mitigations." subject_label="Scouts risk assessment" keywords=[Scouts, risk, assessment, hike, hazards]
[store] Upsert profile: Scouts/risk_assessment_01.pdf
```

### Step 5 — Global planning inputs (using stored profiles)

Build a planning snapshot from:
- all available `file_profile` entries (skipped files are excluded),
- current file locations (root and direct subfolders),
- folder profiles (names + `_index.md` descriptions).

**Logging**:

```text
[global] Files with profiles: 98
[global] Skipped (no usable text): 2
```

### Step 6 — Detect strong subtopic clusters (deterministic pre-pass)

- Compute candidate clusters using stored `keywords` and `subject_label`.
- Treat a cluster as “strong” only when it meets thresholds such as:
  - at least `--min-cluster-size` (if 0/unset, dynamically calculated: 2 for <20 files, 3 for <100, 5 for 100+),
  - semantically narrower than the parent folder theme.

Clusters are evidence for stable folder decisions and for deciding when a split is justified.

**Logging**:

```text
[cluster] Folder=Scouts strong_clusters=1
[cluster]  - "Risk Assessments" size=6 members=[risk_assessment_01.pdf, ...]
```

### Step 7 — Generate a global plan (Planning Agent)

Run an LLM planning agent to produce a global plan that considers:
- existing folders first,
- whether strong clusters justify creating a new (sub)folder and moving a set of files,
- avoiding surprise and over-specific folder creation.

#### 7.1 Global plan output schema

- `actions[]` (ordered):
  - `create_folder {path, index_desc}`
  - `move_file {from, to, rationale}`
  - `update_index {folder_path}`
- `file_decisions[]`:
  - `file_path`
  - `destination_folder_path` (use `(root)` for no move)
  - `rationale`

Save the plan (including rationales) to the local store.

**Logging**:

```text
[plan] Proposed actions:
  - create_folder: Scouts/Risk Assessments
  - move_file: Scouts/risk_assessment_01.pdf -> Scouts/Risk Assessments/ (reason="Risk assessment cluster within Scouts")
  - move_file: (new) risk_assessment_06.pdf -> Scouts/Risk Assessments/
[plan] File decisions saved to store
```

### Step 8 — Critic loop (global plan review) + repair

**Purpose**: reduce surprising refactors and prevent over-splitting.

**Critic output JSON**:
- `acceptable: true/false`
- `critique_rationale`
- `suggested_adjustments[]` (optional)

If `acceptable=false`, run a repair pass to produce a revised plan and re-run the critic. Repeat up to `--critic-iterations`. If the plan remains unacceptable after the iteration cap, the run must not guess: it must report the plan as unaccepted and avoid applying changes.

**Logging**:

```text
[critic] acceptable=false rationale="Split is reasonable, but naming should avoid repeating parent. Prefer Scouts/Risk Assessments."
[repair] iter=1 updated plan: rename new folder to Scouts/Risk Assessments
[critic] iter=1 acceptable=true rationale="Folder split is useful and stable"
```

### Step 9 — Create execution plan output (dry-run default)

Aggregate the accepted plan into:
- folders to create,
- file moves,
- `_index.md` creates/updates,
- skipped files (and reasons).

**Logging**:

```text
[exec] Create folders:
  - Scouts/Risk Assessments
[exec] Moves:
  - Scouts/risk_assessment_01.pdf -> Scouts/Risk Assessments/
[exec] Skipped:
  - scan.png (insufficient extracted text)
```

### Step 10 — Confirm and apply (only with `--apply`)

**Prompt**:
- Prompt once with totals.

**If approved**:
1) create folders,
2) move files,
3) create/update `_index.md` using an idempotent managed section,
4) record applied destinations back into the local store.

**Managed section requirement**:
- `_index.md` updates must be idempotent.
- The tool may overwrite only a clearly marked “managed section”, preserving user-written content outside that section.

**Logging**:

```text
[apply] Create folder: Scouts/Risk Assessments/
[apply] Move: Scouts/risk_assessment_01.pdf -> Scouts/Risk Assessments/
[apply] Update index: Scouts/_index.md (managed section)
[apply] Update index: Scouts/Risk Assessments/_index.md (managed section)
[store] Mark applied: Scouts/risk_assessment_01.pdf -> Scouts/Risk Assessments/
```

### Step 11 — Final report

Always print summary totals, including skipped files.

**Logging**:

```text
[done] Inventory: 100 files
[done] Profiled: 98
[done] Skipped: 2 (insufficient extracted text)
[done] Moves applied: 6
[done] Folders created: 1
[done] Index updated: 2
```

## 7) Folder Naming, Creation, and Splits (Bounded Specificity)

Folder naming and creation must follow `docs/folder_taxonomy_guide.md`. In particular:

- Prefer existing folders by default.
- Create a new folder only when it represents a stable, recurring category.
- Avoid entity-based and time-based folder names.
- Split a folder only when a **strong subtopic cluster** exists (clear theme, critical mass, narrower than parent, predictable future).

## 8) Safety & Data Handling Requirements

- **No deletions**: do not delete files/folders.
- **No user file edits**: do not modify the content of user documents; only move them.
- **Allowed writes**:
  - create subfolders under the target folder,
  - create/update `_index.md` within those subfolders,
  - maintain the local profile/plan store (e.g. `.aifo/`).
- **Bounded depth**: never traverse beyond depth 1 under the target folder.
- **Secrets**: OAuth client/token files must not be committed.

## 9) Error Handling (User-Visible)

- Invalid target folder: fail fast with a clear message.
- Content extraction failures: treat as “no usable text” and skip profiling the file.
- LLM failures: fail explicitly; do not silently guess.
- Unaccepted global plan: report the critique and do not apply changes.

## 10) Acceptance Criteria (for this spec)

A run is considered correct if:

- Inventory includes root + direct subfolders (depth 1 only).
- Files with extracted text < `--min-chars` are skipped from profiling/planning.
- A profile store is used to reuse summaries for unchanged files.
- Strong clusters can justify splits and bulk moves, and weak clusters do not.
- Apply mode prompts once and performs only allowed operations in the correct order.
- `_index.md` updates are idempotent and confined to a managed section.
