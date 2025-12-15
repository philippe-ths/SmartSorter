# Repository Guidelines

## Project Structure & Module Organization

- `ai_folder_sorter/`: main Python package.
  - `cli.py`, `__main__.py`: CLI entrypoint (`python -m ai_folder_sorter`).
  - `planner.py`: builds the sort plan (summaries → decisions → critic loop → actions).
  - `adk_agents.py`: Google ADK agent wrappers and prompt/instruction text.
  - `drive.py`: Google Drive helpers (list/export/move/upsert `_index.md`).
  - `models.py`: dataclasses used across the project.
  - `utils.py`: small utilities (name normalization, stub ID extraction).
- `agent.py`: ADK-friendly entrypoint for running via ADK tooling.
- `docs/`: project documentation.
- `requirements.txt`: runtime dependencies.

## Additional Context (Docs: Read Before Changes)

Treat `docs/` as source-of-truth for behavior. **Read the relevant doc(s) before editing code**:

- Before changing the end-to-end workflow, CLI UX, logging, or step ordering, read `docs/functional_spec.md`.
- Before changing scope/safety/MVP behavior, read `docs/plan.md`.
- Before changing folder naming, “bounded specificity”, or when to create new folders, read `docs/folder_taxonomy_guide.md`.
- Before changing ADK prompts/agents/session-state patterns (especially `ai_folder_sorter/adk_agents.py`), read `docs/adk_general_guide.md`.
- Before changing Drive OAuth, `.gdoc/.gsheet/.gslides` dereferencing, or export/preview behavior, read `docs/google_drive_guide.md`.
- Ignore `docs/.DS_Store` (not documentation).

## Build, Test, and Development Commands

- Install: `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
- Local dry-run (prints summaries/decisions):  
  `python -m ai_folder_sorter --local-path /path/to/folder --show-summaries --critic-iterations 1`
- Apply changes (prompts for `yes`):  
  `python -m ai_folder_sorter --local-path /path/to/folder --apply`
- Drive mode: `python -m ai_folder_sorter --folder-id <DRIVE_FOLDER_ID> --show-summaries`

## Coding Style & Naming Conventions

- Python, 4-space indentation, PEP 8, prefer explicit names and type hints (already used throughout).
- Keep folder names “plain-language, stable, plural nouns”.
- No formatter/linter is enforced; keep diffs minimal and readable.

## Testing Guidelines

- No dedicated test suite yet; run `python -m compileall ai_folder_sorter` and one `--show-summaries` dry-run.

## Commit & Pull Request Guidelines

- No established convention yet; use imperative, descriptive commits.
- PRs: what changed, how to run locally, and a short `--show-summaries` snippet.

## Security & Configuration Tips

- Secrets must never be committed: `.env`, `token.json`, `client_secret_*.json` (already ignored).
- The tool is intentionally **LLM-required**: no heuristic fallback. Expect `GOOGLE_API_KEY` (Gemini) or Vertex AI env + ADC.
- Safety scope: only create folders, move files, and write/overwrite folder `_index.md`; no deletions and no modifying user file contents.
