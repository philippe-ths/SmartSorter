# Process 

### 1) Select target folder (local path)

- User provides a local filesystem path (target folder).

- Treat a “local Google Drive folder” (synced) as normal local storage. No Drive APIs.

- Enforce: operate only within target folder and its direct subfolders.

- **Logging (--logging)**
~~~
[init] Target: /abs/path/to/target
[init] Models: summariser=gemini-2.0-flash-lite, matcher=gemini-2.0-flash-lite
[init] Mode: dry-run (apply=false)
~~~

### 2) Scan the target folder (top-level only)

- List only direct children (no recursion).

- Split into:

   - files to process

   - existing subfolders (candidates for placement)

- **Logging (` --logging `)**

~~~
[scan] Files to process (12):
  - file1.pdf
  - file2.txt
[scan] Existing subfolders (5):
  - Finance
  - Projects
~~~

### 3) Build existing folder context

- For each existing direct subfolder:

   - read ` _index.md ` if present

   - build a folder profile from folder name + short description from ` _index.md `

- **Logging (` --logging `)**

~~~
[context] Folder profiles (5):
  - Finance (index: yes) desc: invoices, tax, banking
  - Projects (index: no)
~~~

### 4) For each top-level file

- Pipeline summary (mental model)

   - Extract bounded text (4.1)
   - Summarise into `file_profile` JSON (4.3)
   - Match to folder → initial `file_plan` (4.4)
   - Critique the plan (5)
   - If rejected: rematch using critique (5.2) up to `--critic-iterations`
   - Aggregate into an execution plan (6)
   - Apply changes only with `--apply` (7)

- 4.1 Extract content (bounded, no fallback)

- Extract text using extension or MIME sniffing.

- Cap extraction at ` --max-chars ` (default 60k).

- If usable extracted text is below ` --min-chars ` (default 500), skip the file.

- No fallback to filename or metadata.

- **Logging (`--logging`)**

~~~
[extract] file1.pdf method=pdf-text chars=43120 (truncated=false)
[extract] scan.png method=image chars=0
[skip] scan.png reason="insufficient extracted text" chars=0 min=500
~~~

### 4.2 Start Google ADK sequence 

- Orchestration layer 

- Sequence ending in Critic Loop

### 4.3 Summarise with Google ADK (Summariser Agent)

- Run ADK LlmAgent (model gemini-2.0-flash-lite) to produce file_profile JSON:

   - summary (max 200 characters)

   - subject_label (max 50 characters)

   - keywords (5–8 words)

- **Logging (--logging)**

~~~
[summarise] file1.pdf summary="This is a paid invoice (number 89500) from Ability Ltd. to Mr Philippe Marr for emergency plumbing work." subject_label="Ability invoice" keywords=[Ability, invoice, november, payments]
[summarise] notes.txt summary="Meeting summery and actions between Philippe and James, meeting fouces on design" subject_label="Call notes" keywords=[Client, meetings, work]
~~~

### 4.4 Match to folder with Google ADK (Folder Matching Agent)

- Run ADK LlmAgent (model gemini-2.0-flash-lite) to produce `file_plan` using: 

   - file_profile (`[{name, summary, keywords}]`)

   - existing_folders: `[{name, _index.md desc}]`

- Output JSON (`file_plan`):

   - file_name

   - target_folder: `{name, exists}`

   - Special case: `target_folder.name="(root)"` means “leave in place” (no move). `exists` should be `true`.

   - index_desc_if_new

   - rationale

- **Logging (`--logging`)**

~~~
[match] file1.pdf -> Finance (exists=true) rationale="Invoice and payment record" 
[match] notes.txt -> Client Onboarding (exists=false) new_index_desc="Clients, meetings, work" rationale="Setup notes and checklist"
~~~

### 5) Critic Loop

- Purpose: reduce “surprising” placements and prevent over-specific folder creation.

- Run ADK LlmAgent (model gemini-2.0-flash-lite) to critique the current `file_plan` against `file_profile`.

- Output JSON (`critique`):

   - file_name

   - target_folder_name

   - acceptable: true/false

   - critique_rationale

   - suggested_adjustments (optional)

       - action: one of ["keep", "use_existing_folder", "create_new_folder", "leave_in_root", "skip"]

     - suggested_folder_name (optional)

     - suggested_index_desc_if_new (optional)

     - suggested_rationale (optional)

~~~
[critique] file1.pdf -> Finance acceptable=true rationale="Invoice and payment record, Finance good fit"
[critique] notes.txt -> Client Onboarding acceptable=false rationale="Not clearly defined as client onboarding."
~~~

- Acceptance criteria (guidance for the critic)

   - Approve when the placement is something “a reasonable human would expect”.
   - Reject when:
     - the target folder is too specific / entity-based / time-based,
     - the rationale does not match the file’s content summary,
     - a better existing folder clearly fits,
     - the plan creates a new folder without a strong, recurring category.

- Iteration behavior

   - The critic loop runs up to `--critic-iterations` critique/rematch cycles per file (default should be small, e.g. 1–2).
   - If `acceptable=true`, the current `file_plan` is final.
   - If `acceptable=false`, the system MUST run the Repair / Rematch step (5.2) to produce a revised `file_plan`, then re-critique.
   - The loop must converge on one of these terminal outcomes:
     - **Accepted move**: choose an existing folder, or a justified new folder, and `acceptable=true`.
     - **Accepted leave-in-root**: set `target_folder.name="(root)"` and `acceptable=true` when creating any folder would be a one-off / low-recurring-value choice.
   - Avoid “false certainty”: if a file does not justify a new folder and there are no suitable existing folders, leaving it in the root is the intended safe default.

### 5.2 Match to folder with Google ADK in Critic Loop

- Run ADK LlmAgent (model gemini-2.0-flash-lite) to produce a revised `file_plan` using:

   - file_profile (`{name, summary, subject_label, keywords}`)

   - existing_folders: `[{name, _index.md desc}]`

   - critique: the JSON critique from step 5

- Output JSON (`file_plan`, same schema as step 4.4):

   - file_name

   - target_folder: `{name, exists}`

   - index_desc_if_new

   - rationale

- Logging (`--logging`) example (one file)

~~~
[match] notes.txt -> Client Onboarding (exists=false) rationale="Setup notes and checklist"
[critic] iter=1 notes.txt -> Client Onboarding acceptable=false critique_rationale="Too specific; not clearly onboarding"
[rematch] iter=1 notes.txt -> Projects (exists=true) rationale="General project/design call notes"
[critic] iter=2 notes.txt -> Projects acceptable=true critique_rationale="Projects is a predictable bucket"
~~~

- Logging (`--logging`) example (reject new folder → leave in root)

~~~
[match] page.html -> Projects (exists=false) rationale="Mentions company projects"
[critic] iter=1 page.html -> Projects acceptable=false critique_rationale="Creating a folder for a single file lacks recurring value"
[rematch] iter=1 page.html -> (root) (exists=true) rationale="No clear reusable category; leave in place"
[critic] iter=2 page.html -> (root) acceptable=true critique_rationale="Leaving in root avoids a surprising one-off folder"
~~~



### 6) Create an execution plan (dry-run default)

- Aggregate:

   - new folders to create

   - moves (file → subfolder)

   - files left in root (explicitly no move)

   - _index.md creates/updates

   - skipped files

- **Logging (--logging)**

~~~
[plan] Create folders:
  - file1.pdf -> Client Onboarding
[plan] Moves:
  - file2.pdf -> Finance/
[plan] Leave in root:
   - page.html (reason="no reusable folder")
~~~

### 7) Confirm and apply (only with --apply)

- Prompt once with totals.

- If approved:

- create new subfolders

- move files

- create/update _index.md using an idempotent managed section

- **Logging (--logging)**

~~~
[apply] Create folder: file2.pdf -> Client Onboarding/
[apply] Move: file1.pdf -> Finance/
[apply] Update index: Finance/_index.md (managed section)
~~~

### 8) Final report

- Always print summary totals, including skipped.

**Logging (--logging)**

~~~
[done] Processed: 12 files
[done] Moved: 10
[done] Folders created: 1
[done] Index updated: 3
[done] Skipped: 2 (insufficient extracted text)
~~~
