# Codex Implementation Contract

## Role
- Codex owns implementation, local harness, repo cleanup, static validation, commits, and push proof.

## Must Do
- Read `AGENTS.md` and `.ai/status/CURRENT_STATE.md` first.
- Keep changes scoped to the active phase.
- Run local validation before commit.
- Push tracked repo changes to GitHub or report the exact blocker.
- Hand live UAT to Antigravity only after the preflight contract is satisfied.

## Must Not Do
- Do not use Antigravity as an iterative debugger.
- Do not accept `REQUEST_ID=N/A` or `build=legacy`.
- Do not patch upload logic without harness coverage.
- Do not mix proven selectors with failed selectors in the same execution path.
- Do not click Generate unless explicitly authorized.
