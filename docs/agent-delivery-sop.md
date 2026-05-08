# Agent Delivery SOP

This repository treats GitHub remote state as the completion boundary for any tracked repo change.

## Mandatory Rule

A repo task is complete only when the final state is auditable on a GitHub remote.

Required delivery evidence:
- Full 40-character commit SHA
- Exact GitHub remote branch name
- Push target
- Exact push result

If any of those items cannot be produced, the task must be reported as `BLOCKED` or `NOT VERIFIED`.

## Default Workflow For All Agents

These rules apply to Codex, Cursor, Claude Code, Antigravity, GitHub Copilot, Gemini, and any other AI agent operating inside this repository.

1. Before changing tracked files, inspect the current branch and reconcile it against the GitHub remote with `git fetch --prune`, ahead/behind checks, and worktree status.
2. Perform the scoped file changes.
3. Run the required local validation for the task scope.
4. Stage, commit, and push the validated change without waiting for a separate reminder from the user.
5. If the workflow requires a PR or merge, update or create the remote artifact and report the exact branch and URL.
6. If push, pull, merge, auth, branch protection, or CI policy blocks delivery, stop calling the task complete and report the exact blocker.

## Forbidden Delivery Behavior

- Leaving validated repo work only on local disk
- Claiming "done" based on local files, local commits, or short SHAs alone
- Hiding push failures behind vague summaries
- Waiting for the user to explicitly ask for a push after a validated tracked-file change
- Reporting partial local state as if GitHub already contains it

## Repo-Specific Binding

- Primary repo instruction surface: `AGENTS.md`
- Claude-specific surface: `CLAUDE.md`
- Gemini-specific surface: `GEMINI.md`
- Copilot-specific surface: `.github/copilot-instructions.md`
- Cursor-specific surface: `.cursor/rules/github-delivery.mdc`
- Contract surface for evidence: `.ai/contracts/GIT_PROOF_REQUIREMENTS.md`

If these surfaces diverge, this SOP is the canonical delivery policy and the agent must still satisfy the remote-proof requirement before declaring completion.
