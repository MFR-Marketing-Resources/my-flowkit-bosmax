# Batch Creative Production Orchestrator — Secondary Research Evidence (v1.1 repair)

**Report version:** 1.1.0-repair  
**CI_STATUS:** `NO_WORKFLOW_RUN_FOUND` for PR #305 (see manifest)

**Classification:** Secondary research only. **Not** implementation authority.

This directory contains forensic audit evidence for high-volume daily creative production (hypothesis: up to ~200 videos + ~200 images/posters per day). Findings are evidence-bound and labeled.

## Authority hierarchy (read first)

This pack **does not override**:

- `AGENTS.md`
- `.ai/status/CURRENT_STATE.md`
- `.ai/contracts/*`
- `.ai/architecture/*`
- `.ai/decisions/*` (including ADR-007 API-first generation)

Use these reports only to prepare a **future** implementation contract after independent review. **No implementation is authorized** by this documentation.

## Examined repository state

- Repository: `MFR-Marketing-Resources/my-flowkit-bosmax`
- Branch examined: `origin/main` at commit `b271f5e162f45c75cf94e88be5c0bc9cadbd6103`
- Generated: `2026-07-11T05:34:23Z`

## Report index

| File | Purpose |
|------|---------|
| `00_EXECUTIVE_FINDINGS.md` | Executive summary + verdict |
| `01_CURRENT_STATE_REPOSITORY_AUDIT.md` | End-to-end architecture trace |
| `02_BATCH_PROMPT_AND_VARIATION_AUDIT.md` | Batch planners (legacy vs WGP) |
| `03_CREATIVE_DIVERSITY_AND_DEDUPE_AUDIT.md` | Variation dimensions + dedupe |
| `04_PRODUCTION_QUEUE_AND_CONCURRENCY_AUDIT.md` | Queues, locks, concurrency |
| `05_IMAGE_AND_POSTER_PIPELINE_AUDIT.md` | IMG / poster vs video |
| `06_DATA_MODEL_AND_STATE_MACHINE_AUDIT.md` | Schema + state machines |
| `07_OPERATOR_WORKFLOW_AND_UX_AUDIT.md` | Operator functional contract |
| `08_FAILURE_RECOVERY_AND_IDEMPOTENCY_AUDIT.md` | Recovery + idempotency |
| `09_THROUGHPUT_CAPACITY_AND_CREDIT_MODEL.md` | 200/day capacity model |
| `10_TARGET_ARCHITECTURE_PROPOSAL.md` | **PROPOSED** target (not approved) |
| `11_GAP_RISK_AND_DECISION_REGISTER.md` | Gaps, risks, decisions |
| `12_IMPLEMENTATION_READINESS_MATRIX.md` | Readiness matrix |
| `13_UNIQUE_CAPACITY_PREFLIGHT_CONTRACT.md` | **PROPOSED** preflight contract |
| `manifest.json` | Machine manifest + provenance |
| `evidence/*.csv` | Traceability matrices (incl. `failed_test_baseline_matrix.csv`) |

## Live credits

**live_credit_spent:** false (no Google Flow generation executed for this audit).
