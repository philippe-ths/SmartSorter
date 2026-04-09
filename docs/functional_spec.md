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
- **Useful refactors**: create role folders for broad categories and project/topic folders for mini-collections.
- **Safety-scoped changes**: only create folders, move files, and write/update `_index.md`.
- **Explainability**: provide short rationales and clear logs when enabled.

## 3) Non-Goals

- Deep semantic taxonomy or maximum topical precision.
- Traversing deeper than the target folder root (no recursion into subfolders for file processing).
- Renaming existing folders, deleting files/folders, or modifying user file contents.
- Guessing based on filename/metadata when content extraction fails.
- Google Drive API integrations in the default local flow (treat synced Drive folders as normal local storage).

## 4) Operating Modes

### 4.1 Local Folder Mode (primary)

- User provides a local filesystem path (the “target folder”).
- The tool only operates within the target folder root.
- It lists direct children only (no recursion).
- Existing subfolders are treated as candidates for file placement, but their contents are not processed.

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
- `--min-role-cluster-size <n>`: minimum cluster size for general role folders (default: 4).
- `--min-project-cluster-size <n>`: minimum cluster size for specific project/topic folders (default: 2).
- `--show-summaries`: print human-readable summaries from stored profiles / plan decisions.
- `--logging`: emit structured log-style lines.

## 6) End-to-End Workflow (Local)

### Step 1 — Select target folder

**Input**: `--local-path`.

**Rules**:
- The target must be an existing directory.
- The tool’s action scope is limited to the target root.

**Logging** (when `--logging`):

```text
[init] Target: /abs/path/to/target
[init] Models: summariser=gemini-2.0-flash-lite, planner=gemini-2.0-flash-lite, critic=gemini-2.0-flash-lite
[init] Mode: dry-run (apply=false)
```

### Step 2 — Inventory scan (top-level only)

**Action**:
- List only **direct children** of the target folder (no recursion).
- Split into:
  - files to process
  - existing subfolders (candidates for placement)

**Logging**:

```text
[scan] Files to process (12):
  - file1.pdf
  - file2.txt
[scan] Existing subfolders (5):
  - Scouts
  - Finance
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
[store] Cached file profiles:
  - file1.pdf:
      summary: "Invoice for services rendered..."
      subject: "Invoice"
      keywords: [invoice, payment, services]
  - file2.docx:
      summary: "Risk assessment for outdoor activity..."
      subject: "Risk Assessment"
      keywords: [risk, assessment, safety, outdoor]
  - image.png: [SKIPPED] reason="insufficient extracted text"
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

### Step 6 — Detect clusters for balanced specificity (deterministic pre-pass)

This step produces **evidence** that the planner uses to decide when to be specific vs general.

#### 6.1 Detect role clusters (general folders)
Role clusters are broad, recurring “what kind of document is this?” groupings.
Examples: risk assessments, activity plans, receipts, meeting notes.

- Use stored `keywords`, `subject_label`, and simple signals to find role clusters.
- Only treat a role cluster as strong when it meets the `--min-role-cluster-size` threshold (default 4).

#### 6.2 Detect project/topic clusters (specific folders)
Project/topic clusters are “mini-collections” like **Camp Gadgets** or **Photographer badge**.

- A project/topic cluster is eligible when:
  - it meets the `--min-project-cluster-size` threshold (default 2), and
  - the files share a clear topic/purpose label, and
  - it would contain more than one file (hard bias against 1-file folders).

#### 6.3 Precedence rule
If a file belongs to a project/topic cluster that will get its own folder, **that placement wins** over a general role folder.

**Logging**:

```text
[cluster] Role clusters:
  - Risk Assessments size=4
  - Activity Plans size=6
[cluster] Project/topic clusters:
  - Camp Gadgets size=2 members=[Camp Gadgets.docx, RA - Camp Gadgets.docx]
```

### Step 7 — Generate a global plan (Planning Agent)

Run an LLM planning agent to produce a global plan that considers:
- existing folders first,
- creating **role folders** when role clusters are strong,
- creating **project/topic folders** when a mini-collection exists,
- avoiding creating one-off folders and surprising splits,
- producing **a placement decision for every file with a profile**, even if it is "leave in root".

#### 7.1 Global plan output schema

The plan must output both:
1) **Actions** (what to do), and
2) **Per-file decisions** (where every file goes and why).

**actions[]** (ordered):
- `create_folder {path, index_desc}`
- `move_file {from, to_folder, rationale}`
- `update_index {folder_path}`

**file_decisions[]** (one entry per file with a profile):
- `file_path`
- `current_folder_path` (use `(root)` when currently in target root)
- `destination_folder_path` (use `(root)` for no move)
- `destination_folder_exists` (true/false)
- `destination_folder_will_be_created` (true/false) — derived from actions
- `move_required` (true/false)
- `rationale` (one line)

Save the plan (including rationales) to the local store.

**Logging** (per-file placements first, then folder creates, then summary):

```text
[plan] File placements:
  - RA - Camp Gadgets.docx -> Camp Gadgets/ (new_folder=true, move=true) rationale="Paired plan + RA mini-collection"
  - Camp Gadgets.docx -> Camp Gadgets/ (new_folder=true, move=true) rationale="Paired plan + RA mini-collection"
  - RA - Pizza ovens.docx -> Risk Assessments/ (new_folder=true, move=true) rationale="Risk assessment role; no matching project folder"
  - 2018-04-28_morning-run.md -> (root) (new_folder=false, move=false) rationale="No recurring cluster; avoid one-off folder"
[plan] Create folders:
  - Camp Gadgets/ (index_desc="Camp Gadgets activity files and related risk assessments")
  - Photographer badge/ (index_desc="Photographer badge materials and supporting docs")
  - Risk Assessments/ (index_desc="Safety/risk docs for activities")
  - Activity Plans/ (index_desc="Plans and instructions for activities")
[plan] Summary: files=10 profiled=10 skipped=1 new_folders=4 moves=9 leave_in_root=1 index_updates=4
[plan] File decisions saved to store
```

### Step 8 — Critic loop (global plan review) + repair

**Purpose**: reduce surprising refactors, prevent over-splitting, and enforce taxonomy rules.

**Critic checks**:
- Are we creating any 1-file folders?
- Are we creating vague/misleading folders (Admin, Family activities, Documents)?
- Are we over-splitting (too many new folders in one run)?
- Are we violating precedence (project folder should win over role folder when it exists)?

**Critic output JSON**:
- `acceptable: true/false`
- `critique_rationale`
- `suggested_adjustments[]` (optional)

If `acceptable=false`, run a repair pass to produce a revised plan and re-run the critic. Repeat up to `--critic-iterations`. If the plan remains unacceptable after the iteration cap, the run must not guess: it must report the plan as unaccepted and avoid applying changes.

**Logging**:

```text
[critic] acceptable=false rationale="Avoided single-file folder; kept item in Risk Assessments."
[repair] iter=1 removed one-off folder: Pizza/
[critic] iter=1 acceptable=true rationale="Balanced: project mini-collections extracted; remaining files grouped into role folders."
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

## 7) Folder Naming, Creation, and Splits (Balanced Specificity)

Folder naming and creation must follow `docs/folder_taxonomy_guide.md`. In particular:

- **Balanced Specificity**: Create **project/topic folders** (specific) for mini-collections (2+ files) and **role folders** (general) for broad, recurring categories.
- **Precedence**: Project/topic folders win over role folders.
- **Hard bias against 1-file folders**: Avoid creating folders for one-off files.
- **Predictability**: Folder names must be plain language and pass the "reasonable human guess" test.
- **Stability**: Avoid entity-based, time-based, or subjective folder names.

## 8) Safety & Data Handling Requirements

- **No deletions**: do not delete files/folders.
- **No user file edits**: do not modify the content of user documents; only move them.
- **Allowed writes**:
  - create subfolders under the target folder,
  - create/update `_index.md` within those subfolders,
  - maintain the local profile/plan store (e.g. `.aifo/`).
- **Bounded depth**: never traverse beyond the target folder root (no recursion for file processing).
- **Secrets**: OAuth client/token files must not be committed.

## 9) Error Handling (User-Visible)

- Invalid target folder: fail fast with a clear message.
- Content extraction failures: treat as “no usable text” and skip profiling the file.
- LLM failures: fail explicitly; do not silently guess.
- Unaccepted global plan: report the critique and do not apply changes.

## 10) Acceptance Criteria (for this spec)

A run is considered correct if:

- Inventory includes only direct children of the target folder (no recursion).
- Files with extracted text < `--min-chars` are skipped from profiling/planning.
- A profile store is used to reuse summaries for unchanged files.
- Balanced specificity is achieved: project/topic folders for mini-collections, role folders for broad categories, and no 1-file folders.
- Apply mode prompts once and performs only allowed operations in the correct order.
- `_index.md` updates are idempotent and confined to a managed section.
