# folder_taxonomy_guide.md

## Design goals
- Fast retrieval for humans
- Low surprise placement
- Stable folder set that ages well
- Gradual improvement as more files arrive

## Core idea: balanced specificity
You want folders to be:
- **more specific** when there is a real mini-collection (2+ files that obviously belong together), and
- **more general** when files are one-offs and only share a broad role (risk assessments, activity plans).

This is a two-tier approach:
1) **Project/Topic folders** (specific, earned)
2) **Role folders** (general, recurring)

## Folder types

### 1) Project/Topic folders (specific, earned)
Use when there is a clear subject/purpose grouping that makes retrieval easier.

Examples:
- `Camp Gadgets/` containing both:
  - `Camp Gadgets.docx`
  - `RA - Camp Gadgets.docx`
- `Photographer badge/` containing:
  - `Photographer badge.gslides`
  - `Photography Badge.gdoc`

**Creation rule**
Create a project/topic folder only if all are true:
- **2+ files** belong together (`--min-project-cluster-size`, default 2)
- the topic name is clear and stable (“Camp Gadgets”, not “Pizza”)
- it is not a 1-file folder (hard bias against one-offs)

### 2) Role folders (general, recurring)
Use for broad categories that recur and act as “shock absorbers”.

Examples:
- `Risk Assessments/` for risk assessment files that do not belong to a specific project folder
- `Activity Plans/` for activity plan files that do not belong to a specific project folder

**Creation rule**
Create a role folder when a role cluster is strong enough to be worth it:
- `--min-role-cluster-size` default 4 (tuneable)
- role folders should remain stable and predictable over time

## Precedence rules (how to decide where files go)
1) **Project/topic folder wins** over role folder when it exists.
   - If “RA - Camp Gadgets” has a matching “Camp Gadgets” plan, put both in `Camp Gadgets/`.
2) **Role folder next** for remaining files of that role.
3) **Leave in root** only when nothing is recurring and creating any folder would be a one-off.

## What “great” looks like (example)
Target folder `Scouts/` contains risk assessments and activity plans.

Great outcome:
- `Camp Gadgets/` contains:
  - `Camp Gadgets.docx`
  - `RA - Camp Gadgets.docx`
- `Photographer badge/` contains:
  - `Photographer badge.gslides`
  - `Photography Badge.gdoc`
- `Risk Assessments/` contains remaining RAs without a paired project folder:
  - `RA - Pizza ovens.docx`
  - `RA - Water Rockets.docx`
  - `Scout Olympics RA.gdoc`
- `Activity Plans/` contains remaining plans:
  - `Poole Cockle Trail tracing the town’s Heritage.gdoc`
  - `Scouts MythBusters .gdoc`
  - `Scouts short Film Evening.gdoc`

## What is acceptable
If there are no clear mini-collections yet, it is fine to start with role folders:
- `Risk Assessments/`
- `Activity Plans/`

When the user adds another related file and a mini-collection becomes obvious (2+ files),
the system should consider creating a project/topic folder and moving the small set.

This is “specificity by accumulation”, not by guessing.

## What is bad (hard constraints)
### 1) Too many 1-file folders
Bad:
- `Pizza/` containing only `RA - Pizza ovens.docx`
- `Water Rockets/` containing only `RA - Water Rockets.docx`

Rule:
- Avoid 1-file folders by default.
- If a category has 1–3 files forever, it probably should have stayed in a role folder.

### 2) Vague or misleading folders
Bad:
- `Admin/` (too vague)
- `Family activities/` (misleading)

Rule:
Folder names must pass the predictability test:
“Could a reasonable human guess this file is in here without reading it?”

### 3) Type buckets or placeholder buckets
Bad:
- `Documents/`, `Files/`, `Misc/`
- `PDFs/`, `Word Docs/`, `Slides/`

Rule:
Foldering is semantic (topic/purpose/role), not file-type based.

## Naming rules
Folder names must:
- be plain language
- describe a role or recognisable category
- be stable over time

Avoid names that are:
- entity-based (people, companies)
- time-based (years, quarters)
- subjective (“important”, “urgent”)

Inside a parent, avoid repeating the parent:
- Good: `Scouts/Risk Assessments/`
- Worse: `Scouts/Scouts Risk Assessments/`

## Success test
A user should be able to:
- guess where a new file will go
- browse folders and understand them instantly
- find an item later without learning “AI logic”
