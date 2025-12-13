# AI File Organiser Plan (Google ADK + Python)

## Goals & Constraints
- User selects one top-level Drive folder.
- Only analyse items directly inside it (no recursion for content analysis).
- Supported items: regular files + native Drive types (Docs, Sheets, Slides, Forms, etc.).
- Allowed actions: create folders, move files, and write/overwrite `_index.md` inside folders.
- Not allowed: delete files, modify file contents, or change sharing/permissions.
- No predefined taxonomy; folder names are proposed dynamically from subject matter.
- Existing folders must be considered first; only create new folders when needed.
- Foldering must be **semantic** (content/intent), not by file type. MIME type is only for extraction.

## System Design
1. **Drive Connector (Python)**
   - List top-level children only: `'{folderId}' in parents and trashed=false`.
   - Least-privilege OAuth scopes: `drive.readonly` + `drive.file`.

2. **Content Extraction**
   - Use MIME type only to choose extraction method (export native Docs/Sheets/Forms to text/csv).
   - Apply extraction limits: capture “enough to summarise” by taking up to `--max-chars` (default 60k).

3. **Summariser Agent (Google ADK)**
   - Input: `{filename, mimeType, textSnippet, metadata}`.
   - Output (structured): `{summary, keywords, subject_label}`.
   - Instruction: ignore file type for subject; describe topic/intent.
   - Implementation: use `google.adk.agents.LlmAgent` with structured JSON output.

4. **Folder Matching & Naming Agent (Google ADK)**
   - Input: `{file_profile, existing_folders:[{name, description}]}`.
   - Output (structured): `{target_folder:{name, exists}, index_description_if_new, rationale}`.
   - Instruction: propose topic folders (projects/activities), never type buckets (e.g., “PDFs”).
   - Implementation: use `google.adk.agents.LlmAgent` and enforce the “no type buckets” rule.

5. **Planner/Executor**
   - Dry-run by default; `--apply` always prompts before writes.
   - Creates any new folders, moves files, and writes `_index.md` (plain text markdown) in touched folders.
   - `_index.md` is overwritten when needed.

## Process
1. For each file in the target folder, extract text and create a semantic summary + keywords.
2. Compare against existing top-level folders (names + `_index.md` if present) to decide placement.
3. Decide whether to reuse a folder or create a new topical folder.
4. Move files into the chosen folders and write/overwrite `_index.md` describing intended contents.

## Documentation-First Rule (Required)
- Before implementing/changing ADK agent behavior, consult the official Google ADK documentation.
- Record doc references (URL + date consulted) in the PR description or commit body for ADK changes.
