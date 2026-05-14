# Git Proof Requirements

## Completion Boundary
- Any tracked repo change is incomplete until the validated result is auditable on a GitHub remote.

## Required Delivery Evidence
- Current branch
- `git status --short`
- `git diff --stat`
- Exact validation commands run
- Pass or fail summary for each validation command
- Full 40-character commit SHA
- Exact remote branch name
- Exact push target
- Exact push result
- PR URL if a PR exists

## Failure Rule
- If push, merge, branch protection, auth, or CI blocks delivery, report `BLOCKED` or `INSTALL_FAILED`.
- Local-only files and local-only commits do not count as completion.
