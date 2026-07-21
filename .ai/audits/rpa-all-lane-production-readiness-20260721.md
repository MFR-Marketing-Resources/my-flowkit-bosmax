# RPA Production Studio — All-Lane Production-Readiness Audit (2026-07-21)

**Mission:** `RPA-G0-RECOVER-AND-ALL-LANES-PRODUCTION-READINESS-20260721`
**Repo state:** `origin/main` at `fc3785f` (Merge PR #440), includes PR #438 (B-12), #439 (B-14/B-15), #440 (stale/foreign retrieval hardening).
**DB:** read-only snapshot copy `flow_agent.db` (659 products; 11 `COPY_APPROVED` copy sets, ALL on product `6483d624`; CHARACTER_REFERENCE=14, SCENE_CONTEXT_REFERENCE=1, STYLE_REFERENCE=0 active+approved; 1 product with a Flow media_id).
**Method:** read-only multi-agent trace (code + DB + live GET), each load-bearing fact independently re-verified. No live fire, zero credit.

This is an **audit record**, not authorization. Governance authority lives in `docs/bosmax-rpa-g0-governance-gate.md`.

## Lane matrix (governing = bulk/production video path)

| Lane | Status | One-line blocker |
|---|---|---|
| **T2V** | `GOVERNANCE_BLOCKED` | Bulk fan-out validates fully green then hard-refuses at `BULK_LIVE_EXECUTION_CERTIFIED=False` (`production_queue_service.py:103` → refusal `:1104-1108`). Owner cert decision, not code. |
| **F2V** | `GOVERNANCE_BLOCKED` | Same `:103` flag; dry-run 2/2/0 proven (`prun_29e8ef41edec48be`) but live fan-out uncertified. |
| **HYBRID** | `GOVERNANCE_BLOCKED` + `DATA_GAP` | Same `:103` flag; and only ONE valid 9:16 anchor exists (`ca_8b573b59176e49ed`, product 6483d624) + HYBRID dialogue pool exhausted (10 combos burned). |
| **I2V** | `GOVERNANCE_BLOCKED` + `DATA_GAP` | Same `:103` flag; dry-run 2/2/0 proven (`prun_d0241297e2fb43a7`); only 1/659 products supplied, 1 global scene-context ref. |
| **IMG** | `NOT_IN_THIS_PIPELINE` | Excluded from `RpaProductionStudioPage.tsx` VIDEO_MODES (`:164`); no WGP package builder. Asset-prep helper feeding F2V/I2V/HYBRID. |

**Sub-lane truth (single-serial, no cert flag):** `ONE_SERIAL_T2V` = the only live-proven lane (best 1/2, engine gates all passed). `ONE_SERIAL_F2V` / `ONE_SERIAL_I2V` code-reachable and fire, but no captured lane-specific live output (I2V only ever proven via the HYBRID fire `g_8845373fbb86`).

## Root cause per lane

- **The uniform wall on all four video lanes is the intentional Stage-3 credit boundary** `BULK_LIVE_EXECUTION_CERTIFIED = False`. Flipping it is an **owner runtime-certification decision**, and flipping it without a proven live bulk run would be a credit-safety regression, not a fix. Every prior defect class (B-03/06/08/09/10/11/14/15) is already closed on `fc3785f`.
- **HYBRID / I2V additionally have a real DATA_GAP**: only product `6483d624` has approved copy; only one valid 9:16 HYBRID anchor exists; only one scene-context reference exists. These are asset-supply gaps for the owner/data team, not code.
- **IMG** is intentionally out of the bulk/production pipeline.

## The one CODE gap found and fixed this round — B-16 (I2V ref-less prepare burns the ledger)

**Fixed in this PR.** Verified end-to-end against code, not hypothesised:

1. `create_i2v_generation_package` sets `status="BLOCKED"` (does **not** raise) when the I2V slot resolver returns blockers — `workspace_generation_package_service.py:504`; resolver emits `MISSING_CHARACTER_REFERENCE` / `MISSING_SCENE_CONTEXT_REFERENCE` at `i2v_semantic_slot_resolver_service.py:153`.
2. Because it returns (no raise), the bulk loop proceeds to burn `record_combination` (`:2188`) and `record_rotation_usage` (`:2208`) for **every** item.
3. `approve_packages` then refuses BLOCKED (`NOT_APPROVABLE_STATUS`) → `BULK_APPROVE_FAILED` (`:2216`) — **after** the ledger rows are committed → stranded `bulk_run_id`; every retry then dies `BULK_REUSE_BATCH_BLOCKED`, permanently consuming N fresh dialogues from a finite approved pool.
4. **This happens at prepare time, before the credit boundary — so the `:103` flag does NOT protect against it.** UI-reachable: `handleBulkPrepare` (`RpaProductionStudioPage.tsx:411`) and the Bulk Prepare button `disabled` (`:1244`) gate only on `bulk_authorizable`, not on reference selection.

**Why I2V-only:** F2V and HYBRID **auto-seed** the frame from the product image (`create_f2v_generation_package` source `PRODUCT_IMAGE_AUTO_SEED`, `:79-82`), so a missing frame never produces BLOCKED status. Gating them would over-reject valid auto-seed runs.

**Fix (front-door, mirrors B-14 model gate):** in `prepare_bulk_fanout_packages`, for `mode=="I2V"` only, run the same resolver once with the supplied references **before** plan/create/burn and raise `BULK_PREPARE_REFUSED:I2V_REFERENCES:<blockers>` if it returns blockers. UI defense-in-depth: an I2V-scoped disable + reason so the doomed click is prevented up front. No gate weakened; zero credit either way; no migration.

## Zero-credit validation available TODAY (up to the credit boundary)

Per lane, on the extension-attached runtime, for product `6483d624`: `bulk-fanout-plan` → `bulk-fanout-prepare` (with the lane's required refs) → dry-run 2/2/0 → BULK_FANOUT gate reaching `BULK_LIVE_EXECUTION_NOT_CERTIFIED`. Proven this session for T2V (fired), F2V/I2V/HYBRID (dry-run). No further code needed to exercise the lanes up to the boundary.

## Next human actions

1. **Owner:** decide the Stage-3 bulk-live certification for each lane (the `:103` flag) — separate per-lane, per §11/§14 of G0; live generation stays `OWNER-ONLY`.
2. **Owner/data:** supply approved copy for products beyond `6483d624`, more 9:16 HYBRID anchors, and more scene-context references — the DATA_GAP that blocks HYBRID/I2V variety.
3. **Reviewer (Faris):** review + merge this PR (B-16 + G0 §18 authority recovery). No agent self-merge (G0 §5).
