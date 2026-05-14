# AI Agent Operating Contract

## Purpose
- Give every AI surface the same repo memory, role boundaries, validation gates, and rejection rules.

## Mandatory Read Order
1. `AGENTS.md`
2. `.ai/status/CURRENT_STATE.md`
3. this file
4. the agent-specific contract for the current tool
5. the relevant architecture and decision files for the active phase

## Global Rules
- Respect the architecture reset.
- Keep proven paths frozen unless local proof shows the frozen path broke.
- Treat unstable paths as rebuild lanes, not as tactical patch sinks.
- Stop if contracts conflict.
- Use auditable GitHub remote state as the completion boundary for tracked changes.

## Live UAT Rule
- Live Google Flow work is forbidden until local harness and preflight pass.
- Antigravity may run one-shot UAT only under the dedicated UAT contract.

## Evidence Rule
- Manual screenshots are not proof by themselves.
- Raw telemetry, exact SHA, validation commands, and remote push proof are mandatory.

## Report Rule
- Reject incomplete reports under `.ai/contracts/REPORT_REJECTION_RULES.md`.
