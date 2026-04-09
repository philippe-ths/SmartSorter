# SmartSorter

An LLM-driven CLI tool that organises loose files into folders using Gemini.

Point it at a cluttered folder and it will analyse each file's content, cluster them by topic, generate a move plan, critique and repair that plan, then (optionally) execute the moves — all without manual sorting.

## Tech Stack

- **Python 3.11+**
- **Google Gemini** — LLM for summarisation, planning, critique, and repair
- **google-genai / google-adk** — SDK and Agent Development Kit
- **pypdf / python-docx / openpyxl** — text extraction from PDF, DOCX, and XLSX

## Prerequisites

1. Python 3.11 or later
2. A Google API key with Gemini access

Set your API key:

```bash
export GOOGLE_API_KEY="your-api-key"
```

Or create a `.env` file:

```
GOOGLE_API_KEY=your-api-key
```

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

### Dry-run (preview the plan)

```bash
python -m ai_folder_sorter --local-path /path/to/folder --show-summaries --logging
```

This scans the folder, extracts text from files, generates a plan, and prints what it would do — without moving anything.

### Apply (execute moves)

```bash
python -m ai_folder_sorter --local-path /path/to/folder --apply
```

Prompts for confirmation before making changes.

### Key options

| Flag | Description |
|------|-------------|
| `--local-path` | Target folder to organise (required) |
| `--apply` | Execute the plan (prompts first) |
| `--show-summaries` | Print human-readable file summaries |
| `--logging` | Emit structured log lines |
| `--critic-iterations N` | Max critic/repair cycles (default: 2) |
| `--max-chars N` | Cap extracted text per file (default: 60000) |

Run `python -m ai_folder_sorter --help` for all options.

## How It Works

```
scan folder → extract text → summarise (LLM) → cluster by topic → plan moves (LLM) → critique (LLM) → repair (LLM) → apply
```

1. **Scan** — Lists top-level files and existing subfolders
2. **Extract** — Pulls text content from PDF, DOCX, XLSX, JSON, and plain text files
3. **Summarise** — LLM generates a structured profile (keywords, subject, placement hints)
4. **Cluster** — Groups files by shared keywords to detect natural topics
5. **Plan** — LLM produces a global move plan, optionally creating new folders
6. **Critique** — A separate LLM pass reviews the plan for surprises or over-splitting
7. **Repair** — Fixes issues flagged by the critic
8. **Apply** — Creates folders, moves files, and updates `_index.md` per folder

## Project Structure

```
ai_folder_sorter/
├── cli.py          # CLI entry point
├── planner.py      # Planning pipeline and application logic
├── adk_agents.py   # LLM client and retry handling
├── extractor.py    # Unified text extraction
├── clustering.py   # Keyword-based file clustering
├── prompts.py      # System prompts for each agent role
├── models.py       # Data structures (profiles, actions, plans)
├── store.py        # Profile persistence (.smartsorter_store/)
├── paths.py        # Path normalisation utilities
└── utils.py        # MIME detection, folder naming, index management
```

## Limitations

- Only processes top-level files; subfolders are placement candidates but not traversed
- Requires readable text content; skips files below 500 chars
- LLM-only — no heuristic fallback if API calls fail
- Does not rename or delete existing files/folders

## License

MIT — see [LICENSE](LICENSE).
