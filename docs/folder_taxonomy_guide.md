# Guide for AI Folder Organisation Inside a User-Chosen Target Folder

---

## Design Goals and Non-Goals

### Goals
- Fast, confident retrieval for humans
- Low surprise placement
- Stable folder set that ages well
- Gradual improvement as more files arrive

### Non-goals
- Maximum semantic specificity
- A folder for every micro-topic
- Automatically reflecting every nuance found in content

If the AI optimises for semantic purity, it will create chaos.

---

## Core Philosophy: Bounded Specificity

The AI may detect many distinctions, but it must only **surface a few**.

You are deliberately forcing the system to live in a narrow band between:
- **Over-segmentation** (too many folders)
- **Under-segmentation** (too few folders)

That band must be enforced by explicit rules, not vibes.

---

## The One Question the AI Must Answer

For each file:

**“Which existing folder name would a reasonable human expect this file to live under?”**

Only if none fit should the AI consider creating a new folder.

Predictability beats correctness. Slightly wrong but expected is often better than technically correct but surprising.

---

## Folder Naming Rules (Human Trust Rules)

Folder names must:
- Use plain language nouns
- Describe **document role / use / category a human recognises**
- Be stable over time

Avoid names that are:
- Entity-based (people, companies, case names, product names)
- Time-based (2024, Q3, “old”, “new”)
- Subjective/emotional (“important”, “urgent”, “interesting”)
- Jargon-y (“knowledge artifacts”, “information assets”)

**Good folder names (generic patterns)**
- Agreements, Correspondence, Reports, Receipts, Research, Plans, Deliverables, Policies, Manuals, Presentations

**Bad folder names**
- “John Smith”, “Client A”, “Project X v2”, “Stuff”, “Misc”, “Important”, “2023”

Entities and time explode folder counts and destroy predictability.

---

## Folder Count Budget (You Must Set One)

Humans can only hold so many categories in their head.

A workable default policy:
- Target: **7 to 12** folders
- Soft cap: **15**
- Hard resistance: **20+** (creation should become extremely rare)

If you allow unlimited folder creation, you will get unlimited mess.

---

## Folder Creation: Strict Thresholds

Creating a new folder is expensive. It changes the user’s mental model.

Create a folder only if all are true:
1. **Recurrence likely:** It will apply to future files, not just this one.
2. **Critical mass:** There are already several files that belong in it (or will imminently).
3. **Name clarity:** The folder can be described in one short sentence that most humans would agree with.

Practical heuristic:
- Do not create a folder unless it plausibly holds **at least ~5 files** within a reasonable time horizon.

If a category has 1–3 files forever, it was a mistake.

---

## Folder Reuse: Default Behaviour

The AI should be conservative:
- Prefer existing folders even if the match is not perfect
- Use broad categories as “shock absorbers”
- Treat new folder creation as a last resort

This prevents the “100 files → 100 folders” failure.

---

## Handling Ambiguity (The System Must Have a Fallback)

Ambiguous files are unavoidable. Plan for it.

You need at least one explicit fallback folder inside the target folder, such as:
- `General`
- `Reference`
- `Unsorted` (only if it is actively reviewed)

Policy:
- If confidence is low, file to fallback
- Do not guess narrowly when uncertain

A visible catch-all is better than silent misclassification.

---

## Granularity Control (How You Avoid “Only Two Folders”)

Under-segmentation happens when the AI is too cautious or the folder set is too generic.

Countermeasure:
- Encourage folder creation when a cluster is clearly recurring and cognitively distinct
- But still obey the folder budget and critical mass threshold

The right behaviour is:
- Start broad
- Split only when the split is obviously useful and will recur

---

## Good vs Bad Outcomes

### Over-segmentation (Bad)
- Many folders with tiny file counts
- Names mirror extracted phrases from content
- Users cannot predict where files go

**Symptoms**
- Folder list looks “smart”
- Retrieval feels worse over time

### Under-segmentation (Bad)
- A few buckets that accumulate everything
- Users must search within huge piles
- Folder names provide no retrieval value

**Symptoms**
- Filing is easy
- Finding later is slow and frustrating

### Bounded specificity (Good)
- Moderate number of folders
- Each folder has a clear, human-recognisable meaning
- Most new files map predictably to an existing folder

---

## Operational Rules for an Evolving Corpus

### Rule 1: Stability at the Top
Once a folder exists, avoid renaming or restructuring unless the user explicitly approves. Churn kills trust.

### Rule 2: Periodic Hygiene
If you allow it, run a maintenance pass occasionally:
- Merge near-duplicate folders
- Collapse folders with very low counts back into broader ones
- Identify ambiguous items sitting in fallback

### Rule 3: Keep Folder Names Consistent
Pick a naming style and stick to it:
- Plural nouns (“Reports”, “Invoices”) tends to work well
- Avoid mixed styles (“Report” vs “Reports”, “Policy” vs “Policies”)

---

## Practical Placement Logic (Simple, Reliable)

When placing a file:
1. Identify the most likely **document role** (what it is used as)
2. Match to best existing folder by role
3. If no folder fits and the pattern is recurring, create a new folder that is role-based and broad
4. If uncertain, put it in fallback

Do not optimise for “most specific concept”. Optimise for “most predictable bucket”.

---

## What You Should Expose to Users (So They Trust It)

At minimum:
- The folder list (obviously)
- A short reason for placement (one line, not an essay)
- A way to override placement

If users cannot correct errors, they will stop using the system.

---

## The Three Failure Modes You Must Defend Against

1. **Folder explosion**: every nuance becomes a folder  
   Fix: folder budget + creation thresholds + entity/time bans

2. **Blob folders**: everything in 2–3 buckets  
   Fix: encourage splits when recurring clusters appear

3. **Unpredictability**: same kind of file goes to different places  
   Fix: conservative reuse, stable naming, and a fallback

---

## Success Test

A user should be able to:
- Guess where a new file will go
- Browse folders and understand them instantly
- Find a previously filed item with minimal search

If they need to “learn the AI’s logic”, the design is wrong.
