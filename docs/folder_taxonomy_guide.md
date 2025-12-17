# folder_taxonomy_guide.md

## Design goals
- Fast retrieval for humans
- Low surprise placement
- Stable folder set that ages well
- Gradual improvement as more files arrive

## Core idea
Folder structure should be driven by **strong subtopic clusters**, not just folder size.

A folder with 20 files can be fine if it stays coherent.
A folder with 20 files becomes a problem when it contains multiple distinct recurring subtopics.

## Stability rules
- Prefer stable structure over constant re-organisation.
- Avoid renames by default.
- Only split when the split is clearly useful and likely to recur.

## Strong subtopic cluster definition
A subtopic cluster is “strong” only when all are true:
1. **Clear theme:** member files share a recognisable role or use (for example, risk assessments).
2. **Critical mass:** cluster has enough files to justify a folder (default heuristic: dynamic based on total file count, e.g., 2 for small batches, 5 for large).
3. **Narrower than parent:** the cluster is a subset of the parent theme (Scouts → Risk Assessments).
4. **Predictable future:** a reasonable person expects more files of this type.

## Split behaviour
When a strong cluster is detected inside a folder:
- Create a new subfolder inside that folder.
- Move all cluster members into the new subfolder.
- Update `_index.md` in both the parent folder and the new subfolder.

Example:
- Folder `Scouts/` contains 20 Scouts-related files.
- 6 files are risk assessments.
- Create `Scouts/Risk Assessments/`.
- Move the 6 risk assessment files (and the newly added one) into that subfolder.

## Folder creation rules
Create a new folder only when:
- no existing folder is a reasonable fit, and
- the category is recurring (not a one-off), and
- it passes the critical mass threshold (dynamic or explicit).

If the category is not recurring, keep the file in place (`(root)` or current folder).

## Naming rules
Folder names must:
- be plain language
- describe a role or recognisable category
- be stable over time

Avoid names that are:
- entity-based (people, companies)
- time-based (years, quarters)
- vague (“Stuff”, “Misc”, “Important”)

### Subfolder naming
Inside a parent folder, avoid repeating the parent context.
- Good: `Scouts/Risk Assessments/`
- Worse: `Scouts/Scouts Risk Assessments/`

## Budget and granularity
Humans can only hold so many categories in their head.
- Prefer a moderate number of folders.
- Split only when it reduces search time and does not create churn.

## Handling ambiguity
If no existing folder fits and no strong recurring cluster exists:
- do not create a new folder
- keep the file in place (`(root)` or current folder)

## Success test
A user should be able to:
- guess where a new file will go
- understand folder meanings instantly
- find an item later without learning “AI logic”
