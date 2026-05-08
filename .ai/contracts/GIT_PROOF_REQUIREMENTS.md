# GIT PROOF REQUIREMENTS

Evidence of the fix must be documented using Git state.

## Required Information
- **Current branch:** `git branch --show-current`
- **Changed files:** `git status --short`
- **Git diff summary:** `git diff --stat`
- **Validation Command:** The exact command run to prove the fix (e.g., `npm test`, `pytest`).
- **Pass/Fail Result:** Snippet of the successful output.
- **Commit SHA:** If committed, the full SHA.
- **PR URL:** If a PR was created.

Any items that cannot be verified must be clearly marked as **NOT VERIFIED**.
