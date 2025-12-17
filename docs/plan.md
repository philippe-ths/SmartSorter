# process.md

## Purpose
Organise a user-chosen **local** target folder by building and storing semantic profiles for files, then generating a **global plan** that can both place new files and refactor existing folders (splits) when strong subtopic clusters emerge.

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
- Enforce: operate only within the target folder and its subfolders.

**Logging (`--logging`)**
```text
[init] Target: /abs/path/to/target
[init] Models: summariser=gemini-2.0-flash-lite, planner=gemini-2.0-flash-lite, critic=gemini-2.0-flash-lite
[init] Mode: dry-run (apply=false)
```

## 2) Inventory scan (bounded depth)
- List files in:
  - the target folder root
  - each **direct subfolder** of the target folder
- Do not traverse deeper than 1 folder level.

**Logging (`--logging`)**
```text
[scan] Root files to consider (12):
  - file1.pdf
  - file2.txt
[scan] Direct subfolders (5):
  - Scouts
  - Finance
[scan] Depth-1 files to consider (88)
```

## 3) Build folder context
- For each direct subfolder:
  - read `_index.md` if present
  - build a folder profile from folder name + short description from `_index.md`

**Logging (`--logging`)**
```text
[context] Folder profiles (5):
  - Scouts (index: yes) desc: scouts admin, activities, plans
  - Finance (index: yes) desc: invoices, tax, banking
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
[extract] Scouts/risk_assessment_01.pdf method=pdf-text chars=43120 (truncated=false)
[extract] scan.png method=image chars=0
[skip] scan.png reason="insufficient extracted text" chars=0 min=500
```

### 4.3 Summarise with Google ADK (Summariser Agent)
- Run ADK `LlmAgent` (model `gemini-2.0-flash-lite`) to produce `file_profile` JSON:
  - `summary` (max 200 characters)
  - `subject_label` (max 50 characters)
  - `keywords` (5–8)
- Save `file_profile` into the local store for future global planning.

**Logging (`--logging`)**
```text
[summarise] risk_assessment_01.pdf summary="Risk assessment for Scouts hike activity, hazards and mitigations." subject_label="Scouts risk assessment" keywords=[Scouts, risk, assessment, hike, hazards]
[store] Upsert profile: Scouts/risk_assessment_01.pdf
```

---

## 5) Global planning inputs (using stored profiles)
- Build a planning snapshot from:
  - all available `file_profile` entries (skipped files are excluded)
  - current file locations (root and direct subfolders)
  - folder profiles (names + `_index.md` descriptions)

**Logging (`--logging`)**
```text
[global] Files with profiles: 98
[global] Skipped (no usable text): 2
```

## 6) Detect strong subtopic clusters (deterministic pre-pass)
- Compute candidate clusters using stored `keywords` and `subject_label`.
- Clusters are used as evidence for splits and for more stable folder decisions.
- Only treat a cluster as “strong” when it meets thresholds (example defaults):
  - `--min-cluster-size` (default 5)
  - cluster is semantically narrower than the parent folder theme

**Logging (`--logging`)**
```text
[cluster] Folder=Scouts strong_clusters=1
[cluster]  - "Risk Assessments" size=6 members=[risk_assessment_01.pdf, ...]
```

## 7) Generate a global plan with Google ADK (Planning Agent)
- Run ADK `LlmAgent` (model `gemini-2.0-flash-lite`) to produce a global `plan`.
- The plan must consider:
  - existing folders first
  - whether strong clusters justify creating a new (sub)folder and moving a set of files
  - avoiding surprise and over-specific folder creation

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
  - create_folder: Scouts/Risk Assessments
  - move_file: Scouts/risk_assessment_01.pdf -> Scouts/Risk Assessments/ (reason="Risk assessment cluster within Scouts")
  - move_file: (new) risk_assessment_06.pdf -> Scouts/Risk Assessments/
[plan] File decisions saved to store
```

---

## 8) Critic loop (global plan review)
- Purpose: reduce surprising refactors and prevent over-splitting.
- Run ADK `LlmAgent` (model `gemini-2.0-flash-lite`) to critique the **global** plan.
- Critic output JSON:
  - `acceptable: true/false`
  - `critique_rationale`
  - `suggested_adjustments[]` (optional), such as:
    - “do not create folder, cluster too small”
    - “use existing folder instead of new folder”
    - “keep files in place for stability”

**Logging (`--logging`)**
```text
[critic] acceptable=false rationale="Split is reasonable, but naming should avoid repeating parent. Prefer Scouts/Risk Assessments."
```

### 8.1 Repair pass (only if critic rejects)
- Run the Repair Agent (same model) with:
  - the original plan
  - the critic feedback
- Produce a revised plan, then re-run the critic.
- Repeat up to `--critic-iterations` (default 1–2).

**Logging (`--logging`)**
```text
[repair] iter=1 updated plan: rename new folder to Scouts/Risk Assessments
[critic] iter=1 acceptable=true rationale="Folder split is useful and stable"
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
  - Scouts/Risk Assessments
[exec] Moves:
  - Scouts/risk_assessment_01.pdf -> Scouts/Risk Assessments/
  - risk_assessment_06.pdf -> Scouts/Risk Assessments/
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
[apply] Create folder: Scouts/Risk Assessments/
[apply] Move: Scouts/risk_assessment_01.pdf -> Scouts/Risk Assessments/
[apply] Update index: Scouts/_index.md (managed section)
[apply] Update index: Scouts/Risk Assessments/_index.md (managed section)
[store] Mark applied: Scouts/risk_assessment_01.pdf -> Scouts/Risk Assessments/
```

## 11) Final report
- Always print summary totals, including skipped.

**Logging (`--logging`)**
```text
[done] Inventory: 100 files
[done] Profiled: 98
[done] Skipped: 2 (insufficient extracted text)
[done] Moves applied: 6
[done] Folders created: 1
[done] Index updated: 2
```
