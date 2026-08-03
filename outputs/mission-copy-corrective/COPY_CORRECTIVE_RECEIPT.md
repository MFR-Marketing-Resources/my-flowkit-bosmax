# COPY-CORRECTIVE RECEIPT — BOSMAX-COPY-CORRECTIVE-ONCE-AND-FOR-ALL-20260803

## Executive verdict
**299 / 402 genuine strict-valid after the PR #609 FINAL governance correction
(B1–B4); 103 honestly contained (never fabricated).**
PR #608's "402/402 production-ready copy" was rejected with evidence and replaced
with truth: a fail-closed authority + free revalidation of salvageable copy + paid
replacement of the genuine residual, capped at two attempts. The final governance
round then hardened approval-time semantic grounding (B1) and formula/sales presence
(B2). Applying B2 faithfully **exposed 101 legacy `AI_COPY_ASSIST` sets that were
approved under the old fail-open validator with NO formula-QA verdict** — these are
now quarantined (recoverable, not deleted), not silently passed. Reporting the honest
299 rather than a preserved-400 is the whole point of this mission: the count follows
the evidence, never the target.

> Correction note: an earlier draft of this receipt claimed 400/402. That number
> predated the B2 fail-closed formula/sales gate. Under B2 (which the owner mandated),
> a formula-lane set with no formula verdict must not pass; 101 such sets fail and are
> contained. The current authoritative number is **299** (`final_reconciliation.json`,
> `final_containment_proof.json`).

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
| **Strict-valid approved products** | **299** |
| Without strict-valid | 103 |
| — of which: formula-verdict-missing (quarantined, NEEDS_REVALIDATION) | 101 |
| — of which: generic Outcome-B (owner decision) | 2 |
| strict-valid WITH generic filler | 0 |
| strict-valid MISSING semantic receipt | 0 |
| non-quarantined approved sets re-checked (independent) | 2356 |
| non-quarantined approved sets that are INVALID (fail-open leak) | **0** |

- Attempt-1 paid successes: 115 · Attempt-2 paid successes: 2
- Total provider calls (all paid attempts): **130** · tokens in/out: 249,251 / 418,796 ·
  **estimated cost $0.528** (deepseek-v4-flash).

## PR #609 FINAL governance correction (B1–B4, one round, no provider calls)
- **B1 — real semantic grounding AT APPROVAL.** `approve_copy_set` now runs
  `assess_semantic_grounding` on the set against the current approved PI snapshot and
  FAILS CLOSED (`COPY_SET_UNGROUNDED`) if not grounded; the receipt persists the
  grounding evidence (overlap tokens/count, per-attribute grounding, snapshot id).
  The validity authority now REQUIRES that grounding evidence plus a verified
  genericness verdict (`generic=false`) — a receipt without them fails
  (`SEMANTIC_REVIEW_NOT_GROUNDED` / `…_NO_USP_GROUNDING` / `…_GENERICNESS_UNVERIFIED`).
- **B2 — formula/sales presence, no silent pass.** Missing `formula_validation` /
  `sales_clarity` no longer passes. A set is valid only with a PRESENT+passing verdict,
  a DURABLE `NOT_APPLICABLE` (`{applicable:false, reason, route, evaluator, evaluated_at}`)
  for a genuine deterministic lane, or an exact per-gate override. NOT_APPLICABLE is
  **never inferred from absence** and is **not** written for the AI formula lane.
  Faithful application quarantined **101** legacy `AI_COPY_ASSIST` sets (verdict-less,
  `COPY_SET_FORMULA_OPEN`) — see `final_revalidation_ledger.jsonl`.
- **B3 — provider usage map cleanup.** `_usage_by_call_id` is drained on every terminal
  path (parse-failure and success in `generate_candidate` / `complete_json`) and bounded
  ≤512 so a long concurrent run cannot leak it (`test_ai_copy_provider_usage_map.py`).
- **B4 — Outcome-B audit reconstruction.** Both Outcome-B products' real Attempt-1/2
  provider outcomes were reconstructed from `provider_call_ledger.jsonl` into the
  manifest / results / quarantine reasons.
- **Independent containment proof** (`final_containment_proof.json`): all **2356**
  non-quarantined approved sets in the cohort re-evaluated through
  `evaluate_copy_set_id` → **0 invalid** (no fail-open leak); integrity ok, FK 0.

## Quarantine enforcement (`quarantine_enforcement_proof.json`)
Both Outcome-B products: ACTIVE + preserved, classification ≠ APPROVED_COPY_VALID,
rotation pool 0, binding blocked on every approved set → provably non-executable.

## Outcome B (owner decision) — `outcome_b_manifest.json`
1. `8ea29ec2…` FATIMA INSTANT SARUNG SYRIA (hijab) — NEEDS_REVALIDATION (2nd attempt provider error).
2. `9daaa6b9…` "100 Doa Taubat…" (religious text) — BLOCKED (copy is intrinsically claim-unsafe).
Both preserved, non-executable; recommend supplying product-specific facts or accepting non-copy-eligible.

## Integrity / immutability (re-verified post-B1–B4, `final_containment_proof.json`)
- DB integrity_check: **ok** · foreign_key_check: **0** · product **659** · copy_set **3003**
  (unchanged — grew earlier, ZERO deletions this round).
- Product Intelligence snapshots/drafts unchanged; no product/Copy-Set/provenance/audit deletion.

## Tests
- **B1–B4 targeted matrix: 91 passed, 0 failures** — validity authority, approval
  formula/grounding gate, revalidation engine, PI-stale invalidation, AI-copy-assist,
  provider usage-map (B3).
- Copy-eligibility enforcement: **21 passed, 0 failures**.
- Broad copy/validity matrix (35 suites): **402 passed, 3 failed**. The 3 failures are
  `test_copy_binding_workspace_integration.py` (receipt-less hand-inserted fixture) and
  are **PRE-EXISTING** — reproduced identically against committed HEAD `10cd848` with my
  B1–B4 edits swapped out, so they are NOT introduced by this round. They are a stale
  test fixture unrelated to the four blockers and out of scope per "fix the 4 blockers
  only" + Engineering Lockdown; left untouched, flagged for a separate task.
- `git diff --check` clean.

## Merge / runtime
- I open the PR; **owner merges** (no self-merge). **Shared runtime NOT restarted.**
