# Codex Review Prompt: BOSMAX Dual-Route Multi-Mode Temporal Extension v0.1

## Review Objective

Review the contract file:

- `docs/authority/working/BOSMAX_DUAL_ROUTE_MULTI_MODE_TEMPORAL_EXTENSION_CONTRACT_v0_1.md`

Treat this as a forensic architecture review against the current `_ref_flowkit` checkout only.

## Review Context

- Repo root: `C:\Users\USER\Desktop\_ref_flowkit`
- Reviewed git SHA: `6935930ddd6ef45cb9725d1d9805ab9435116a4f`
- Remote baseline: `origin/main`
- Contract status: `DRAFT_FOR_CODEX_FORENSIC_REVIEW`
- Implementation status: `NO_CODING_AUTHORIZED`

## Review Constraints

- Do not assume the BOSMAX SaaS repo is present in this checkout.
- Do not treat external operator-pack files as repo-verified unless physically proven in source control.
- Do not propose implementation as already authorized.
- Preserve strict separation between:
  - `VERIFIED FROM REPO`
  - `NOT VERIFIED YET`
  - `ASSUMPTIONS`
  - `RECOMMENDATIONS`
- Call out any statement in the contract that presents an unverified claim as fact.
- Keep `NO_CODING_AUTHORIZED` in force unless a separate explicit authorization exists.

## Required Review Output

Return all sections below in this exact order:

### 1. Executive verdict

- `PASS`
- `REVISE`
- `BLOCK`

### 2. Exact git SHA reviewed

- Full 40-character SHA actually reviewed.

### 3. Existing repo fit map

- Map each major contract area to current repo proof:
  - product intelligence
  - prompt compiler
  - operator routes
  - mode surfaces
  - batch queue
  - telemetry
  - output history
  - external operator-pack dependency

### 4. Files likely affected

- List the most likely future files, routes, services, contracts, or UI surfaces that would be touched if implementation were later authorized.

### 5. Existing code/models/routes/functions already satisfying part of contract

- Identify current files, modules, tables, fields, services, and routes that already partially satisfy the contract.

### 6. Duplications or contradictions with current architecture

- Identify where the contract duplicates existing concepts or collides with current naming, routes, data flow, or operator semantics.

### 7. Missing database fields or migrations

- Identify only what appears missing if this contract were ever implemented.
- Distinguish clearly between:
  - already present fields
  - likely new fields
  - speculative fields

### 8. Missing UI surfaces

- Identify any missing planner, registry, preview, validation, queue, or history surfaces relative to the contract.

### 9. Missing validation gates

- Identify which fail-closed checks are already present and which are missing.

### 10. Google Flow automation unknowns

- Enumerate current orchestration unknowns, especially:
  - composer state
  - prompt injection
  - asset upload
  - render completion detection
  - extend vs insert detection
  - per-block logging
  - failure recovery

### 11. Batch queue risks

- Review temporal block expansion, retry semantics, resume-from-last-block behavior, queue saturation, and mismatch risk with current batch architecture.

### 12. Security and prompt-injection risks

- Review internal ID leakage, unsafe prompt synthesis, untrusted preview values, and operator-pack dependency risks.

### 13. Product truth and claim-boundary risks

- Review where the contract may still allow unsupported claims, invented dimensions, unsafe handling assumptions, or unsupported persona inference.

### 14. Proposed minimal implementation phases

- Recommend the smallest safe later implementation sequence.
- Keep the answer phase-gated and fail-closed.

### 15. Required amendments before final contract

- List exact edits needed before this contract can be marked final.

### 16. What must remain `NO_CODING_AUTHORIZED`

- State which work must stay contract-only and must not proceed into implementation from this document alone.

## Reporting Format

Return the final review using this structure:

- `STATUS`
- `VERIFIED`
- `NOT VERIFIED`
- `REMOTE PROOF`
- `RISKS`
- `NEXT DECISION`

Additional requirements:

- Under `STATUS`, include the executive verdict.
- Under `REMOTE PROOF`, include the exact SHA reviewed and whether the file exists on the working branch being reviewed.
- Under `RISKS`, prioritize contradictions, missing proof, and accidental implementation scope drift.
- Under `NEXT DECISION`, state whether the contract should be revised, approved for finalization, or blocked pending repo reconciliation.

## Review Standard

This is a forensic contract review, not a feature brainstorm.

- Prefer contradictions over compliments.
- Prefer precise file-level fit over general architecture talk.
- Prefer repo-grounded proof over memory.
- Prefer `REVISE` whenever the contract overstates current repo truth.
