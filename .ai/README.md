# AI Contract Pack

This directory is the repository-level memory and operating system for BOSMAX Flow Kit agents.

## Read Order
1. `../AGENTS.md`
2. `status/CURRENT_STATE.md`
3. `contracts/AI_AGENT_OPERATING_CONTRACT.md`
4. the agent-specific contract for the current tool
5. the relevant architecture and decision files for the current phase

## Directory Map
- `status/` = current repo state, frozen paths, blocked work, and allowed next work
- `contracts/` = hard operating rules, validation gates, telemetry requirements, and report rejection rules
- `architecture/` = the architecture reset, golden path, test pyramid, upload strategy, and planned registries
- `decisions/` = ADRs that explain why the reset exists and what is locked
- `prompts/` = copy-paste prompts for future Codex, ChatGPT, Claude Code, Cursor, and Antigravity sessions
- `research/` = archived source material copied from the user-provided research files

## Non-Negotiables
- No live Google Flow before local harness and preflight pass.
- No Antigravity debugging.
- No `REQUEST_ID=N/A`.
- No `build=legacy` acceptance.
- No tactical upload patches without local harness coverage.
