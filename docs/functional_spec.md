# SmartSorter / AI Folder Sorter — Functional Specification

## 1) Purpose

SmartSorter is a CLI tool that organises files inside a user-chosen target folder by:

- reading a bounded preview of each file’s content,
- generating a small structured summary (`file_profile`),
- selecting an existing subfolder or proposing a single new subfolder (`file_plan`),
- running a critic loop to reduce surprising placements and over-specific folder creation,
- producing an execution plan and (optionally) applying it.

The system is intentionally LLM-driven: it does not provide a non-LLM heuristic fallback.


## 2) Design Goals

- **Predictable filing**: pick the folder a “reasonable human would expect”.
- **Low-surprise moves**: avoid narrow, time-based, or entity-based folder creation.
- **Stable folder set**: prefer reusing existing folders; create new folders only when justified.
- **Safety-scoped changes**: only create folders, move files, and write/update `_index.md`.
- **Explainability**: provide short rationales for placements and clear logs when enabled.


## 3) Non-Goals

- Deep semantic taxonomy or maximum topical precision.
- Recursively reorganising nested folders.
- Renaming existing folders, deleting files/folders, or modifying user file contents.
- Guessing based on filename/metadata when content extraction fails.


## 4) Operating Modes

### 4.1 Local Folder Mode (primary)

- User provides a local filesystem path (the “target folder”).
- The tool only operates within:
  - the target folder itself, and
  - its **direct subfolders**.
- No recursion.

### 4.2 Local Google Drive “stub” files (synced Drive folders)

If the target folder is a locally synced Drive folder, Google-native documents may appear as stubs:

- `.gdoc`, `.gsheet`, `.gslides`, `.gform`

For these, the tool may dereference stubs using the Google Drive API to fetch an export preview (see `docs/google_drive_guide.md`).

### 4.3 Google Drive Folder Mode (if enabled by the CLI)

Some deployments may allow operating on a Drive folder ID (rather than a local path). If supported, Drive-specific behaviors (auth, export, etc.) are defined by `docs/google_drive_guide.md`.


## 5) User Experience (CLI)

### 5.1 Core commands

- Dry-run (default):
  - builds a plan and prints what it would do.
- Apply mode:
  - requires an explicit `--apply` flag and a single confirmation prompt.

### 5.2 Expected CLI flags (behavioral contract)

The following flags define the intended UX/behavior:

- `--local-path <path>`: target folder on local filesystem.
- `--folder-id <id>`: target Drive folder ID (if Drive mode is supported).
- `--apply`: actually create folders/move files/update `_index.md`.
- `--show-summaries`: print `file_profile` summaries (useful for inspection).
- `--critic-iterations <n>`: max critic loop iterations per file.
- `--max-chars <n>`: cap extracted preview text (default: 60000).
- `--min-chars <n>`: minimum extracted text to proceed (default: 500). Files below this are skipped.
- `--logging`: emit structured log-style lines (examples below).

If CLI help text ever diverges from this spec, treat the CLI as a bug unless intentionally re-scoped in `docs/plan.md`.


## 6) High-Level Workflow

This section defines the end-to-end behaviour for a run against a local target folder.

### Step 1 — Select target folder

**Input**: `--local-path`.

**Rules**:
- The target must be an existing directory.
- The tool’s action scope is limited to the target and its direct subfolders.

**Logging** (when `--logging`):

```
[init] Target: /abs/path/to/target
[init] Models: summariser=gemini-2.0-flash-lite, matcher=gemini-2.0-flash-lite
[init] Mode: dry-run (apply=false)
```

### Step 2 — Scan target folder (top-level only)

**Action**:
- List only direct children of the target folder.
- Split into:
  - “files to process” (top-level files),
  - “existing subfolders” (direct subfolders).

**Logging**:

```
[scan] Files to process (12):
  - file1.pdf
  - file2.txt
[scan] Existing subfolders (5):
  - Finance
  - Projects
```

### Step 3 — Build existing folder context

For each existing direct subfolder:

- Read `_index.md` if present.
- Build a folder profile from:
  - folder name,
  - `_index.md` short description if available.

**Logging**:

```
[context] Folder profiles (5):
  - Finance (index: yes) desc: invoices, tax, banking
  - Projects (index: no)
```

### Step 4 — Process each top-level file

#### 4.1 Extract bounded content (no fallback)

**Action**:
- Extract text using an extractor determined by extension/MIME sniffing.
- Cap extraction at `--max-chars`.

**Skip rule**:
- If usable extracted text is below `--min-chars`, the file is skipped.
- The tool must not fall back to filename, path, timestamps, or other metadata.

**Logging**:

```
[extract] file1.pdf method=pdf-text chars=43120 (truncated=false)
[extract] scan.png method=image chars=0
[skip] scan.png reason="insufficient extracted text" chars=0 min=500
```

#### 4.2 Summarise (Summariser Agent)

**Input**:
- file name
- extracted text (bounded)

**Output**: `file_profile` JSON:

- `summary` (max 200 characters)
- `subject_label` (max 50 characters)
- `keywords` (5–8 words)

**Logging**:

```
[summarise] file1.pdf summary="This is a paid invoice (number 89500) from Ability Ltd. to Mr Philippe Marr for emergency plumbing work." subject_label="Ability invoice" keywords=[Ability, invoice, november, payments]
```

#### 4.3 Match to folder (Folder Matching Agent)

**Inputs**:
- `file_profile` (at minimum `{name, summary, keywords}`)
- `existing_folders` list with `{name, desc}` where `desc` may come from `_index.md`

**Output**: `file_plan` JSON:

- `file_name`
- `target_folder`: `{name, exists}`
- `index_desc_if_new` (only if `exists=false`)
- `rationale`

**Logging**:

```
[match] file1.pdf -> Finance (exists=true) rationale="Invoice and payment record"
[match] notes.txt -> Client Onboarding (exists=false) new_index_desc="Clients, meetings, work" rationale="Setup notes and checklist"
```

### Step 5 — Critic loop

**Purpose**: reduce surprising placements and prevent over-specific folder creation.

**Input**:
- current `file_plan`
- `file_profile`

**Output**: `critique` JSON:

- `file_name`
- `target_folder_name`
- `acceptable` (boolean)
- `critique_rationale`
- `suggested_adjustments` (optional)
  - `action`: one of `["keep", "use_existing_folder", "create_new_folder", "skip"]`
  - `suggested_folder_name` (optional)
  - `suggested_index_desc_if_new` (optional)
  - `suggested_rationale` (optional)

**Acceptance guidance** (normative):
- Approve when the placement is what a reasonable human would expect.
- Reject when:
  - proposed folder is too specific, entity-based, or time-based,
  - rationale does not match the summary,
  - a better existing folder clearly fits,
  - creating a new folder lacks strong recurring value.

**Iteration behaviour**:
- Run up to `--critic-iterations` per file.
- If `acceptable=true`, the current plan is final.
- If `acceptable=false`, run a rematch step using the critique as additional input.
- If still unacceptable after max iterations: **do not guess**; mark the file as skipped for planning (no move).

**Logging example**:

```
[match] notes.txt -> Client Onboarding (exists=false) rationale="Setup notes and checklist"
[critic] iter=1 notes.txt -> Client Onboarding acceptable=false critique_rationale="Too specific; not clearly onboarding"
[rematch] iter=1 notes.txt -> Projects (exists=true) rationale="General project/design call notes"
[critic] iter=2 notes.txt -> Projects acceptable=true critique_rationale="Projects is a predictable bucket"
```

### Step 6 — Create execution plan (dry-run default)

Aggregate results across all files:

- folders to create
- file moves
- `_index.md` creates/updates
- skipped files (and reasons)

**Logging**:

```
[plan] Create folders:
  - Client Onboarding
[plan] Moves:
  - file2.pdf -> Finance/
```

### Step 7 — Confirm and apply (only with `--apply`)

**Prompt**:
- Prompt once with totals (folders to create, moves, index updates, skipped).

**If approved**:
- Create new subfolders.
- Move files.
- Create/update `_index.md` using an idempotent managed section.

**Managed section requirement**:
- `_index.md` updates must be idempotent.
- The tool may overwrite only a clearly marked “managed section”, preserving user-written content outside that section.

**Logging**:

```
[apply] Create folder: Client Onboarding/
[apply] Move: file1.pdf -> Finance/
[apply] Update index: Finance/_index.md (managed section)
```

### Step 8 — Final report

Always print a summary, including skipped files.

**Logging**:

```
[done] Processed: 12 files
[done] Moved: 10
[done] Folders created: 1
[done] Index updated: 3
[done] Skipped: 2 (insufficient extracted text)
```


## 7) Folder Naming & Creation Rules (Bounded Specificity)

Folder creation and naming must follow the repository’s folder taxonomy rules (see `docs/folder_taxonomy_guide.md`). In particular:

- Prefer existing folders by default.
- New folders must be plain-language, stable, human-recognisable categories.
- Avoid entity-based and time-based folder names.
- Treat new folder creation as expensive; require strong recurring utility.

This philosophy applies both in matching and in the critic acceptance criteria.


## 8) Safety & Data Handling Requirements

- **No deletions**: do not delete files/folders.
- **No user file edits**: do not modify the content of user documents; only move them.
- **Allowed writes**:
  - create subfolders under the target folder,
  - create/update `_index.md` within those subfolders.
- **No recursion**: never traverse beyond the target folder’s direct children.
- **Secrets**: OAuth client/token files must not be committed.


## 9) Error Handling (User-Visible)

- Invalid target folder: fail fast with a clear message.
- Content extraction failures: treat as “no usable text” and apply the `--min-chars` skip rule.
- LLM call failures: fail the affected file (or the run) explicitly; do not silently guess.
- Critic loop exhaustion: skip the file rather than forcing a placement.


## 10) Acceptance Criteria (for this spec)

A run is considered correct if:

- Only top-level files are considered, and only direct subfolders are targets.
- Files with extracted text < `--min-chars` are skipped.
- Plans include folder creation, moves, index updates, and skipped files.
- Apply mode prompts once and performs only the allowed operations.
- Folder naming aligns with the bounded-specificity rules.
- `_index.md` updates are idempotent and confined to a managed section.
