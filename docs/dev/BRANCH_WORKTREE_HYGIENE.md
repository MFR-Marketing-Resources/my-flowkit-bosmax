# Branch / Worktree Hygiene Protocol

**Mandatory for every agent (Claude, Codex, Cursor, human) working in this repo.**
This is process discipline only — it changes no product/runtime logic.

## Background — the PR #281 contamination incident
`_ref_flowkit` is often a **shared working checkout** with multiple agents working
concurrently. A concurrent agent switched the shared checkout's `HEAD` to their
feature branch (`feat/bulk-generation-orchestrator-v1`, commit `43b594a`, PR #280).
A Phase 2A branch was then created with `git checkout -b` **without verifying HEAD
was on `main`**, so the new branch's parent became `43b594a`. As a result **PR #281
was not isolated**: its diff carried PR #280's 9 bulk-generation files plus the 8
intended Phase 2A files (17 total), and the report **overstated cleanliness** by
inferring "PR = 8 files" from "commit = 8 files".

Outcome: `main` ended up logically correct (each commit applied once, targeted
tests green), but the process failed. These rules prevent a repeat.

## Rules

### Rule 1 — Isolated worktree per task
Every new task creates its own isolated worktree from `origin/main`:
```
git fetch origin
git worktree add --detach <temp-path> origin/main
cd <temp-path>
git switch -c <new-branch>
```

### Rule 2 — Never branch from current HEAD on a shared checkout
Do **not** `git checkout -b` from wherever HEAD happens to be. Branch **explicitly**
from `origin/main` (Rule 1, or `git switch --detach origin/main && git switch -c <name>`).

### Rule 3 — Pre-branch verification
Before creating a branch, verify and record:
```
git status --short          # working tree state
git branch --show-current   # where HEAD is
git rev-parse HEAD          # exact commit HEAD points at
```

### Rule 4 — PR final-report evidence (required)
Every PR's final report MUST include:
```
git merge-base origin/main HEAD
git diff --name-only origin/main...HEAD     # the PR's ACTUAL changed files (3-dot)
git diff --name-only HEAD~1..HEAD           # for a single-commit PR
```
…plus a **PR-changed-files vs intended-owned-files matrix** (assert equal; flag any
extras). **Never infer "PR = N files" from "commit = N files."**

### Rule 5 — Dirty/unrelated files → stop
If `git status --short` shows unrelated/dirty files (another agent's WIP), **stop**
and create an isolated worktree from `origin/main` instead of branching in place.

### Rule 6 — Never touch another agent's work
Never `stash`, edit, commit, or `switch` another agent's files or branch in the
shared checkout. Read-only verification is fine via a throwaway worktree
(`git worktree add --detach <tmp> origin/main` … `git worktree remove --force <tmp>`).

### Rule 7 — Scope of this document
This is a **docs-only** protocol. It authorizes **no** feature coding, no Phase 2B
poster-compositor work, and no runtime/product changes.

## Quick checklist
- [ ] `git fetch origin`
- [ ] isolated worktree from `origin/main`
- [ ] `git rev-parse HEAD == origin/main` before committing
- [ ] PR report shows `git diff --name-only origin/main...HEAD`
- [ ] changed files == intended owned files (no extras)
