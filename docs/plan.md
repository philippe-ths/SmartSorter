# process.md

## Purpose
Organise a user-chosen **local** target folder by:
1) building and storing semantic profiles for each file (summary + keywords),
2) producing a **global plan** that uses all stored profiles at once,
3) creating a **balanced** folder structure that is sometimes more specific (when there is a real mini-collection) and sometimes more general (when files are one-offs).

This is designed to avoid both:
- **folder explosion** (lots of 1-file folders), and
- **blob folders** (everything dumped into “Documents”).

## Models (explicit)
All Google ADK agents use a fast, low-cost model:
- Summariser Agent (`LlmAgent`): `gemini-2.0-flash-lite`
- Planning Agent (`LlmAgent`): `gemini-2.0-flash-lite`
- Critic Agent (`LlmAgent`): `gemini-2.0-flash-lite`
- Repair Agent (only when critic rejects): `gemini-2.0-flash-lite`

---

## 1) Select target folder (local path)
- User provides a local filesystem path (target folder).
- Treat a synced “local Google Drive” folder as normal local storage. No Drive APIs.
- Enforce: operate only within the target folder.

**Logging (`--logging`)**
```text
[init] Target: /abs/path/to/target
[init] Models: summariser=gemini-2.0-flash-lite, planner=gemini-2.0-flash-lite, critic=gemini-2.0-flash-lite
[init] Mode: dry-run (apply=false)
```

## 2) Scan the target folder (top-level only)
- List only **direct children** of the target folder (no recursion).
- Split into:
  - files to process
  - existing subfolders (candidates for placement)

**Logging (`--logging`)**
```text
[scan] Files to process (12):
  - RA - Camp Gadgets.docx
  - Camp Gadgets.docx
[scan] Existing subfolders (0):
```

## 3) Build existing folder context
- For each existing direct subfolder:
  - read `_index.md` if present
  - build a folder profile from folder name + short description from `_index.md`

**Logging (`--logging`)**
```text
[context] Folder profiles (5):
  - Risk Assessments (index: yes) desc: safety/risk docs for activities
  - Activity Plans (index: yes) desc: plans and instructions for activities
```

## 4) Build or refresh file profiles (store-first)
### 4.1 Profile store lookup
- Maintain a local store of file intelligence (for example, under `.aifo/` in the target folder).
- For each file in the inventory:
  - if a stored profile exists and the file is unchanged (mtime/size), reuse it
  - otherwise, extract and summarise, then upsert the profile

**Logging (`--logging`)**
```text
[store] Loaded profiles: 83
[store] Needs summarise: 17
```

### 4.2 Extract content (bounded, no fallback)
- Extract text using extension or MIME sniffing.
- Cap extraction at `--max-chars` (default 60k).
- If usable extracted text is below `--min-chars` (default 500), **skip** the file.
- No fallback to filename or metadata.

**Logging (`--logging`)**
```text
[extract] RA - Camp Gadgets.docx method=docx-text chars=43120 (truncated=false)
[extract] scan.png method=image chars=0
[skip] scan.png reason="insufficient extracted text" chars=0 min=500
```

### 4.3 Summarise with Google ADK (Summariser Agent)
- Run ADK `LlmAgent` (model `gemini-2.0-flash-lite`) to produce `file_profile` JSON:
  - `summary` (max 200 characters)
  - `subject_label` (max 50 characters)
  - `keywords` (5–8)
- Save `file_profile` into the local store for global planning.

**Logging (`--logging`)**
```text
[summarise] RA - Camp Gadgets.docx summary="Risk assessment for Scouts camp gadgets activity." subject_label="Scouts camp gadgets" keywords=[Scouts, risk, assessment, camp, gadgets]
[store] Upsert profile: RA - Camp Gadgets.docx
```

---

## 5) Global planning inputs (using stored profiles)
- Build a planning snapshot from:
  - all available `file_profile` entries (skipped files are excluded)
  - current file locations (root and existing subfolders)
  - folder profiles (names + `_index.md` descriptions)

**Logging (`--logging`)**
```text
[global] Files with profiles: 98
[global] Skipped (no usable text): 2
```

## 6) Detect clusters for balanced specificity (deterministic pre-pass)
This step produces **evidence** that the planner uses to decide when to be specific vs general.

### 6.1 Detect role clusters (general folders)
Role clusters are broad, recurring “what kind of document is this?” groupings.
Examples: risk assessments, activity plans, receipts, meeting notes.

- Use stored `keywords`, `subject_label`, and simple signals (like “RA -” prefixes) to find role clusters.
- Only treat a role cluster as strong when it meets a threshold:
  - `--min-role-cluster-size` (default 4)

### 6.2 Detect project/topic clusters (specific folders)
Project/topic clusters are “mini-collections” like **Camp Gadgets** or **Photographer badge**.

- A project/topic cluster is eligible when:
  - `--min-project-cluster-size` (default 2), and
  - the files share a clear topic/purpose label, and
  - it would contain more than one file (hard bias against 1-file folders).

### 6.3 Precedence rule (important)
If a file belongs to a project/topic cluster that will get its own folder, **that placement wins** over a general role folder.
Example: “RA - Camp Gadgets” goes to `Camp Gadgets/` (with its paired plan) rather than `Risk Assessments/`.

**Logging (`--logging`)**
```text
[cluster] Role clusters:
  - Risk Assessments size=4
  - Activity Plans size=6
[cluster] Project/topic clusters:
  - Camp Gadgets size=2 members=[Camp Gadgets.docx, RA - Camp Gadgets.docx]
  - Photographer badge size=2 members=[Photographer badge.gslides, Photography Badge.gdoc]
```

## 7) Generate a global plan with Google ADK (Planning Agent)
- Run ADK `LlmAgent` (model `gemini-2.0-flash-lite`) to propose a global plan that:
  - reuses existing folders first,
  - creates **role folders** when role clusters are strong,
  - creates **project/topic folders** when a mini-collection exists,
  - avoids creating one-off folders.

### 7.1 Plan output schema (global)
The plan outputs actions and per-file destinations.
- `actions[]` (ordered):
  - `create_folder {path, index_desc}`
  - `move_file {from, to, rationale}`
  - `update_index {folder_path}`
- `file_decisions[]`:
  - `file_path`
  - `destination_folder_path` (use `(root)` for no move)
  - `rationale`

Save the plan (including per-file rationale) into the local store.

**Logging (`--logging`)**
```text
[plan] Proposed actions:
  - create_folder: Camp Gadgets
  - create_folder: Photographer badge
  - create_folder: Risk Assessments
  - create_folder: Activity Plans
  - move_file: RA - Camp Gadgets.docx -> Camp Gadgets/ (reason="paired plan + RA mini-collection")
  - move_file: RA - Pizza ovens.docx -> Risk Assessments/ (reason="risk assessment role; no paired project folder")
[plan] File decisions saved to store
```

---

## 8) Critic loop (global plan review)
- Purpose: prevent folder explosion, bad names, and surprising splits.
- Run ADK `LlmAgent` (model `gemini-2.0-flash-lite`) to critique the **global** plan.

Critic checks (minimum set):
- Are we creating any 1-file folders?
- Are we creating vague/misleading folders (Admin, Family activities, Documents)?
- Are we over-splitting (too many new folders in one run)?
- Are we violating precedence (project folder should win over role folder when it exists)?

**Logging (`--logging`)**
```text
[critic] acceptable=true rationale="Balanced: project mini-collections extracted; remaining files grouped into role folders."
```

### 8.1 Repair pass (only if critic rejects)
- Run the Repair Agent with the plan + critic feedback.
- Re-run critic up to `--critic-iterations` (default 1–2).

**Logging (`--logging`)**
```text
[repair] iter=1 removed one-off folder: Pizza/
[critic] iter=1 acceptable=true rationale="Avoided single-file folder; kept item in Risk Assessments."
```

---

## 9) Create execution plan output (dry-run default)
- Aggregate the final accepted plan into:
  - folders to create
  - file moves
  - `_index.md` creates/updates
  - skipped files

**Logging (`--logging`)**
```text
[exec] Create folders:
  - Camp Gadgets/
  - Photographer badge/
  - Risk Assessments/
  - Activity Plans/
[exec] Moves:
  - RA - Camp Gadgets.docx -> Camp Gadgets/
  - Camp Gadgets.docx -> Camp Gadgets/
[exec] Skipped:
  - scan.png (insufficient extracted text)
```

## 10) Confirm and apply (only with `--apply`)
- Prompt once with totals.
- If approved:
  1) create folders
  2) move files
  3) create/update `_index.md` using an idempotent managed section
  4) record applied destinations back into the local store

**Logging (`--logging`)**
```text
[apply] Create folder: Camp Gadgets/
[apply] Move: RA - Camp Gadgets.docx -> Camp Gadgets/
[apply] Update index: Camp Gadgets/_index.md (managed section)
[store] Mark applied: RA - Camp Gadgets.docx -> Camp Gadgets/
```

## 11) Final report
- Always print summary totals, including skipped.

**Logging (`--logging`)**
```text
[done] Inventory: 100 files
[done] Profiled: 98
[done] Skipped: 2 (insufficient extracted text)
[done] Moves applied: 14
[done] Folders created: 4
[done] Index updated: 4
```
