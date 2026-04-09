# SmartSorter (AI Folder Sorter)

Organises top-level files inside a target folder into its direct subfolders using an LLM-driven plan.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Dry-run (local)

```bash
python -m ai_folder_sorter --local-path /path/to/folder --show-summaries --critic-iterations 1 --logging
```

## Apply (local)

```bash
python -m ai_folder_sorter --local-path /path/to/folder --apply
```

## Notes

- This tool requires LLM access (Gemini via `GOOGLE_API_KEY` or Vertex/ADC).
- Behavior is specified in `docs/functional_spec.md`.
