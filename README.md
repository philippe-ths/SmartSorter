# SmartSorter (MVP)

Minimal viable implementation of the plan in `docs/plan.md`: pick a Google Drive folder, analyze only its direct children, propose semantic folders, and (optionally) create/move/write `_index.md`.

## Setup

1) Create and activate a virtualenv

2) Install dependencies:

```bash
pip install -r requirements.txt
```

3) Configure Google Drive auth (recommended: installed-app OAuth):

```bash
export GOOGLE_OAUTH_CLIENT_FILE="/absolute/path/to/client_secret.json"
# Optional (defaults to token.json next to the client file)
export GOOGLE_OAUTH_TOKEN_FILE="/absolute/path/to/token.json"
```

## Run (dry-run by default)

```bash
python -m ai_folder_sorter --folder-id "<DRIVE_FOLDER_ID>"
```

## Apply changes (prompts before writing)

```bash
python -m ai_folder_sorter --folder-id "<DRIVE_FOLDER_ID>" --apply
```

## Notes

- This MVP requires Google ADK + a working LLM configuration; it will fail fast if summaries cannot be produced.
- This MVP uses Google Drive API exports for Google-native files (Docs/Sheets/Slides) and downloads text-like binaries when feasible.
- `_index.md` is created/overwritten only in folders that were created or received moved files.
- Local PDF summarization requires `pypdf` to extract text before summarization.
