# COPY-CORRECTIVE RECEIPT — BOSMAX-COPY-CORRECTIVE-ONCE-AND-FOR-ALL-20260803

## Executive verdict
**OUTCOME B — 400 / 402 genuine strict-valid; 2 owner-decision (never fabricated).**
PR #608's "402/402 production-ready copy" was rejected with evidence and replaced
with truth: a fail-closed authority + free revalidation of salvageable copy + paid
replacement of the genuine residual, capped at two attempts, with 2 products honestly
quarantined rather than forced green.

## Starting / final main
- Starting `origin/main`: `fbb43fd957d04dc52c3ea62789a6fab456bd3e0e` (PR #608 merge)
- Final `origin/main`: unchanged — corrective work is on branch
  `claude/copy-final-corrective-repair`; **owner merges the PR** (no self-merge).

## PR #608 defects confirmed (file:line + timestamps)
1. Generic/synthetic fallback copy — `outputs/mission-copy-final/copy_final_writer.py`
   & holdout scripts; 137/402 products carried filler in an approved set.
2. Mass approval w/o semantic review — `writer_summary.json` 09:46:41Z→09:47:00Z = **19s / 402 products**.
3. Validity fails OPEN — `copy_set_validity_service.py:131` (missing verdict passed).
4. Over-broad override — `:139` any `approval_override` bypassed both gates.
5. Non-atomic approval — `copy_set_service.approve_copy_set` set APPROVED then stamped lineage in `try/except: pass`.
6. Swallowed stale-invalidation — `product_intelligence_review_draft_service.py:1491` `except Exception: pass`.
7. Invalid copy misclassified as STALE — `classify_product_copy` collapsed all reasons.
8. Reporting/readiness could hide eval failure (null / whole-metric fail-open).
9. No operator copy-quality dashboard truth. 10. No baseline / durable proof.

## Retained architecture (repaired, not discarded)
Copy-set validity authority, PI-snapshot lineage columns, readiness/reporting/binding
wiring, stale-copy concept, recovery artifacts — all kept and made fail-closed.

## Fail-closed changes (all tested)
- Validity: present-and-pass evidence (completeness, safety, **semantic-review receipt**),
  per-gate override that never bypasses safety, auditable generic/synthetic detector,
  reason-aware classes (UNSAFE/GENERIC/INCOMPLETE/MISSING_REVIEW/FORMULA/SALES/INVALID_LINEAGE/STALE),
  `VALIDITY_EVALUATION_FAILED` sentinel.
- Approval: single atomic write (status+receipt+lineage+quarantine-clear), generic blocked at the door,
  fails closed without a current PI snapshot.
- PI invalidation: non-silent bounded-retry durable quarantine; dynamic validity fail-closes meanwhile.
- Reporting/readiness fail-closed per product; dashboard leads with strict production-readiness.
- Execution enforcement: binding + workspace generation/execution packages resolve through the
  strict fail-closed seam; rotation/poster exclude quarantine.
- Token-boundary placeholder safety fix (a real "6XXXL" size is not an "xxx" placeholder).
- Reliable per-call provider usage under concurrency (`ai_copy_provider_adapter`).

## Data closure (live DB, backup-guarded, ZERO deletions)
- Fresh restore point: `flow_agent_pre_corrective_20260803T101600Z.db` (integrity ok, FK 0).
- Free strict revalidation (no provider): **283/402 closed**, 2340 sets revalidated, 119 quarantined
  (after a grounding-robustness fix recovered 69 false-quarantines from English-PI/Malay-copy).
- Paid replacement (concurrent, 10 workers / single serialized writer, **max 2 attempts**):
  **117 residual closed** (115 on attempt 1, 2 on attempt 2), **2 quarantined after two attempts**.

## Final reconciliation (authoritative — via the strict authority, `final_reconciliation.json`)
| Metric | Value |
|---|---|
| ACTIVE canonical eligible cohort | 402 |
| **Strict-valid approved products** | **400** |
| Without strict-valid (Outcome B) | 2 |
| strict-valid WITH generic filler | 0 |
| strict-valid MISSING semantic receipt | 0 |

- Attempt-1 paid successes: 115 · Attempt-2 paid successes: 2
- Total provider calls (all paid attempts): **130** · tokens in/out: 249,251 / 418,796 ·
  **estimated cost $0.528** (deepseek-v4-flash).

## Quarantine enforcement (`quarantine_enforcement_proof.json`)
Both Outcome-B products: ACTIVE + preserved, classification ≠ APPROVED_COPY_VALID,
rotation pool 0, binding blocked on every approved set → provably non-executable.

## Outcome B (owner decision) — `outcome_b_manifest.json`
1. `8ea29ec2…` FATIMA INSTANT SARUNG SYRIA (hijab) — NEEDS_REVALIDATION (2nd attempt provider error).
2. `9daaa6b9…` "100 Doa Taubat…" (religious text) — BLOCKED (copy is intrinsically claim-unsafe).
Both preserved, non-executable; recommend supplying product-specific facts or accepting non-copy-eligible.

## Integrity / immutability
- DB integrity_check: ok · foreign_key_check: 0 · ACTIVE 402 / ARCHIVED 257 · copy_set 3003 (grew, no deletions).
- Product Intelligence snapshots/drafts unchanged; no product/Copy-Set/provenance/audit deletion.

## Tests
- Branch focused matrix: **279–288 passed, 0 failures** (20 suites).
- origin/main baseline: 251 passed / 0 failures → **0 mission-induced failures**
  (2 pre-existing scene-cluster failures are unrelated). Dashboard `npm run build` clean; 25 vitest pass.
- `git diff --check` clean.

## Merge / runtime
- I open the PR; **owner merges** (no self-merge). **Shared runtime NOT restarted.**
