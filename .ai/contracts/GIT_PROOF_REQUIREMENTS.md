# GIT PROOF REQUIREMENTS

Evidence of a fix must be documented using Git state and GitHub remote state.

## Mandatory Remote Delivery Rule

Any tracked repo change is incomplete until the validated result is auditable on a GitHub remote through a commit plus push, or is explicitly reported as blocked with the exact failing reason.

Do not wait for the user to remind the agent to push validated tracked-file changes.

## Required Information
- **Current branch:** `git branch --show-current`
- **Changed files:** `git status --short`
- **Git diff summary:** `git diff --stat`
- **Validation Command:** The exact command run to prove the fix (e.g., `npm test`, `pytest`).
- **Pass/Fail Result:** Snippet of the successful output.
- **Commit SHA:** The full 40-character SHA after commit.
- **Remote branch:** The exact GitHub remote branch name.
- **Push target:** The exact push destination.
- **Push result:** The exact push result.
- **PR URL:** If a PR was created.

## Failure Rule

If push, pull, merge, auth, branch protection, or CI policy blocks delivery, the task must be reported as `BLOCKED` or `NOT VERIFIED`. Local-only files and local-only commits are not enough to call the work complete.
