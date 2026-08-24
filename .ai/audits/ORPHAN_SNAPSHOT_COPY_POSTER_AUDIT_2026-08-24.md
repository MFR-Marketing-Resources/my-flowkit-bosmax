<!-- markdownlint-disable MD013 -->

# Forensic Audit — `_ref_flowkit-official-visual` Orphaned Copy/Poster Feature Set

- **Role:** Senior Software Archaeologist / Git Forensics Engineer
- **Task type:** Read-only investigation. No code changed, no merges, no deletions, no commits.
- **Date:** 2026-08-24
- **Snapshot audited:** `C:\Users\USER\Desktop\_archived_flowkit_worktrees\_ref_flowkit-official-visual` (plain file snapshot; **no `.git`** — confirmed, files dated 2026-08-15)
- **Live repo:** `C:\Users\USER\Desktop\_ref_flowkit` → `MFR-Marketing-Resources/my-flowkit-bosmax`, default branch `main`
- **Live HEAD at audit:** `7cefd03` (branch `codex/restore-owner-all-products-ux`)
- **Coverage:** all 759 remote branches fetched (`git fetch --all --prune --tags`); GitHub PR API queried as `farisdatosheikh`
- **Access:** Full local filesystem + full git history + GitHub API. No source limitation.

---

## A. Executive Summary

**All 45 files are SUPERSEDED / INTENTIONALLY REMOVED. There are ZERO orphaned files. No P0 finding.**

| Verdict | Count |
| --- | ---: |
| **SUPERSEDED / INTENTIONALLY REMOVED** | **45** |
| RENAMED / REIMPLEMENTED ELSEWHERE (1:1 file rename) | 0 |
| **NEVER MERGED / ORPHANED (P0)** | **0** |
| INCONCLUSIVE | 0 |

The 45 files are the **legacy "copy-set" / "poster-copy" copy-storage feature cluster** (built July–early-Aug 2026). They were **deliberately deleted from `main` on 2026-08-18/19** by a documented, **owner-authorized** retirement (**ADR-011**, Accepted 2026-08-14) that made **Copy Register V2** the sole copy authority. The deletions landed through exactly **two merged PRs** via **three deletion commits**, all confirmed ancestors of both `origin/main` and the current `HEAD`:

| Deletion commit | Date | PR | Files removed |
| --- | --- | --- | ---: |
| `60d6b1c` — *"complete legacy copy-storage V2 cutover — zero normal callers"* | 2026-08-19 | **[#808](https://github.com/MFR-Marketing-Resources/my-flowkit-bosmax/pull/808)** (merged 2026-08-18) | 26 |
| `b6fc722` — *"wip(D4): retire maintenance mode + tombstone legacy routers; delete retired tests"* | 2026-08-19 | **[#809](https://github.com/MFR-Marketing-Resources/my-flowkit-bosmax/pull/809)** (merged 2026-08-18) | 15 |
| `daf3dc3` — *"test(copy-retirement): rebaseline verify-gate to the V2 / receipt-native contract"* | 2026-08-19 | **[#809](https://github.com/MFR-Marketing-Resources/my-flowkit-bosmax/pull/809)** (merged 2026-08-18) | 4 |

**Anti-orphan proof (content identity):** every one of the 45 snapshot files was blob-hashed (`git hash-object`) and **matched a historical git blob on that exact path** in `main`'s lineage (45/45 `HIST_MATCH`, 0 `NO_MATCH`). The snapshot contains **no novel or divergent engineering work** — it is a plain 2026-08-15 checkout of code that was intentionally removed four days later.

**Recommendation: the cleanup may proceed. The folder is safe to delete.** Nothing unique or unrecoverable lives in it; every file is fully recoverable from `main`'s git history at the SHAs cited below.

---

## B. Proof Matrix (all 45 files individually accounted for)

Legend — **ADD** = commit that introduced the file on `main` lineage · **DEL** = commit that deleted it (all on `origin/main` **and** `HEAD`) · **PR** = merged pull request that carried the deletion · **Content** = snapshot blob vs. git history for that path.

### Group 1 — Frontend copy/poster UI + clients — deleted by `60d6b1c` (PR #808) — 26 files

| # | File | ADD (introduced) | DEL | PR | Content |
| ---: | --- | --- | --- | --- | --- |
| 1 | `dashboard/src/api/copyComponents.ts` | `4dc3170` 2026-07-24 | `60d6b1c` | #808 | HIST_MATCH |
| 2 | `dashboard/src/api/copySets.ts` | `3bd7168` | `60d6b1c` | #808 | HIST_MATCH (==pre-del) |
| 3 | `dashboard/src/api/copywritingReadiness.ts` | `56c1e74` 2026-07-08 | `60d6b1c` | #808 | HIST_MATCH |
| 4 | `dashboard/src/api/creativeSupply.ts` | `7409553` 2026-07-30 | `60d6b1c` | #808 | HIST_MATCH |
| 5 | `dashboard/src/api/posterCopyFit.ts` | `6122efb` 2026-07-08 | `60d6b1c` | #808 | HIST_MATCH |
| 6 | `dashboard/src/api/posterCopyRecommendations.ts` | `aea7259` 2026-07-07 | `60d6b1c` | #808 | HIST_MATCH |
| 7 | `dashboard/src/api/posterCopySets.ts` | `667ffc7` 2026-07-10 | `60d6b1c` | #808 | HIST_MATCH |
| 8 | `dashboard/src/components/BulkAngleSuggestionsPanel.test.tsx` | `1608aa0` 2026-07-27 | `60d6b1c` | #808 | HIST_MATCH |
| 9 | `dashboard/src/components/BulkAngleSuggestionsPanel.tsx` | `1608aa0` 2026-07-27 | `60d6b1c` | #808 | HIST_MATCH |
| 10 | `dashboard/src/components/CopyComponentsPanel.test.tsx` | `4dc3170` 2026-07-24 | `60d6b1c` | #808 | HIST_MATCH |
| 11 | `dashboard/src/components/CopyComponentsPanel.tsx` | `4dc3170` 2026-07-24 | `60d6b1c` | #808 | HIST_MATCH |
| 12 | `dashboard/src/components/CreativeSupplyFactoryPanel.test.tsx` | `7409553` 2026-07-30 | `60d6b1c` | #808 | HIST_MATCH |
| 13 | `dashboard/src/components/CreativeSupplyFactoryPanel.tsx` | `7409553` 2026-07-30 | `60d6b1c` | #808 | HIST_MATCH |
| 14 | `dashboard/src/components/copywriting/CopywritingReadinessCard.test.tsx` | `56c1e74` 2026-07-08 | `60d6b1c` | #808 | HIST_MATCH |
| 15 | `dashboard/src/components/copywriting/CopywritingReadinessCard.tsx` | `56c1e74` 2026-07-08 | `60d6b1c` | #808 | HIST_MATCH |
| 16 | `dashboard/src/components/poster/PosterAngleCopyStep.test.tsx` | `667ffc7` 2026-07-10 | `60d6b1c` | #808 | HIST_MATCH |
| 17 | `dashboard/src/components/poster/PosterAngleCopyStep.tsx` | `667ffc7` 2026-07-10 | `60d6b1c` | #808 | HIST_MATCH |
| 18 | `dashboard/src/components/poster/PosterComposePanel.tsx` | `667ffc7` 2026-07-10 | `60d6b1c` | #808 | HIST_MATCH |
| 19 | `dashboard/src/components/poster/guided/PosterGuidedShell.test.tsx` | `39c6f3c` 2026-07-10 | `60d6b1c` | #808 | HIST_MATCH |
| 20 | `dashboard/src/components/poster/guided/PosterGuidedShell.tsx` | `39c6f3c` 2026-07-10 | `60d6b1c` | #808 | HIST_MATCH |
| 21 | `dashboard/src/components/workspace/CopySelectionPanel.test.tsx` | `21a7626` | `60d6b1c` | #808 | HIST_MATCH |
| 22 | `dashboard/src/components/workspace/CopySelectionPanel.tsx` | `3bd7168` | `60d6b1c` | #808 | HIST_MATCH |
| 23 | `dashboard/src/components/workspace/rpaSelectors.component.test.tsx` | `0c2fbc6` | `60d6b1c` | #808 | HIST_MATCH |
| 24 | `dashboard/src/pages/ImgCockpitPage.tsx` | `e97582c` | `60d6b1c` | #808 | HIST_MATCH |
| 25 | `dashboard/src/poster/guided/usePosterGuidedWorkflow.ts` | `39c6f3c` 2026-07-10 | `60d6b1c` | #808 | HIST_MATCH |
| 26 | `tests/ui/test_img_cockpit_page_ui_contract.py` | `e97582c` | `60d6b1c` | #808 | HIST_MATCH |

### Group 2 — Backend copy/poster service tests — deleted by `b6fc722` (PR #809) — 15 files

| # | File | ADD (introduced) | DEL | PR | Content |
| ---: | --- | --- | --- | --- | --- |
| 27 | `tests/api/test_poster_copy_sets_api.py` | `667ffc7` 2026-07-10 | `b6fc722` | #809 | HIST_MATCH |
| 28 | `tests/unit/test_ai_copy_assist_service.py` | `73dda29` 2026-07-05 | `b6fc722` | #809 | HIST_MATCH |
| 29 | `tests/unit/test_copyset_approval_formula_gate.py` | `fd0e6e0` 2026-07-08 | `b6fc722` | #809 | HIST_MATCH |
| 30 | `tests/unit/test_copy_component_author.py` | `be99e81` 2026-07-24 | `b6fc722` | #809 | HIST_MATCH |
| 31 | `tests/unit/test_copy_component_capacity.py` | `2f4121a` 2026-07-24 | `b6fc722` | #809 | HIST_MATCH |
| 32 | `tests/unit/test_copy_composer.py` | `6329685` 2026-07-24 | `b6fc722` | #809 | HIST_MATCH |
| 33 | `tests/unit/test_copy_compose_persist.py` | `6e9be87` 2026-07-24 | `b6fc722` | #809 | HIST_MATCH |
| 34 | `tests/unit/test_copy_pi_stale_invalidation.py` | `e3ea432` 2026-08-03 | `b6fc722` | #809 | HIST_MATCH |
| 35 | `tests/unit/test_copy_pool_readiness.py` | `cd3cf64` 2026-07-20 | `b6fc722` | #809 | HIST_MATCH |
| 36 | `tests/unit/test_copy_revalidation_engine.py` | `5275925` 2026-08-03 | `b6fc722` | #809 | HIST_MATCH |
| 37 | `tests/unit/test_copy_rotation_service.py` | `dd95d7a` 2026-07-19 | `b6fc722` | #809 | HIST_MATCH |
| 38 | `tests/unit/test_copy_safety_placeholder.py` | `2b1dff4` 2026-08-03 | `b6fc722` | #809 | HIST_MATCH |
| 39 | `tests/unit/test_copy_set_service.py` | `b75870a` 2026-07-04 | `b6fc722` | #809 | HIST_MATCH (==pre-del) |
| 40 | `tests/unit/test_copy_usage_service.py` | `74161df` 2026-07-06 | `b6fc722` | #809 | HIST_MATCH |
| 41 | `tests/unit/test_poster_copy_set_service.py` | `667ffc7` 2026-07-10 | `b6fc722` | #809 | HIST_MATCH |

### Group 3 — Verify-gate rebaseline tests — deleted by `daf3dc3` (PR #809) — 4 files

| # | File | ADD (introduced) | DEL | PR | Content |
| ---: | --- | --- | --- | --- | --- |
| 42 | `tests/api/test_copywriting_readiness_api.py` | `56c1e74` 2026-07-08 | `daf3dc3` | #809 | HIST_MATCH |
| 43 | `tests/api/test_copy_sets_api.py` | `b75870a` 2026-07-04 | `daf3dc3` | #809 | HIST_MATCH |
| 44 | `tests/unit/test_poster_copy_governance.py` | `aee3bb0` 2026-07-08 | `daf3dc3` | #809 | HIST_MATCH |
| 45 | `tests/unit/test_poster_prompt_draft_service.py` | `fcb8904` 2026-07-07 | `daf3dc3` | #809 | HIST_MATCH (==pre-del) |

**Totals:** 26 + 15 + 4 = **45/45 accounted for.** Every row: absent from `HEAD` and `origin/main`; a cited ADD on main lineage; a cited DEL on main (in HEAD); snapshot content identical to a historical git blob.

---

## Why "SUPERSEDED" and not "RENAMED / REIMPLEMENTED"

Git recorded these as **deletions (`D` status)**, not renames — no rename detection fired, because the replacement is a **different architecture** (Copy Register V2 / Landbank V3), not a moved file. The **capability** was reimplemented; the **files** were removed. Per the retirement commit `60d6b1c` and **ADR-011**, the functional successors now live on `main`:

- **Legacy copy authoring/selection clients** (`copySets.ts`, `copyComponents.ts`, `posterCopySets.ts`, `copywritingReadiness.ts`, `creativeSupply.ts`, `posterCopyFit.ts`, `posterCopyRecommendations.ts`) → **`dashboard/src/api/copyRegisterV2.ts`** + Copy Authority / Landbank pages (`CopyAuthorityDetailPage.tsx`, `CopywritingLandbankDatabasePage.tsx`).
- **Legacy backend copy_set / poster_copy_set services** (exercised by the deleted `tests/unit/test_copy_*`, `test_poster_copy_*`) → **`agent/api/copy_register_v2.py`**, **`agent/services/copy_register_v2_service.py`**, now covered by `tests/unit/test_copy_register_v2_*.py`, `tests/api/test_copy_register_v2_api.py`, `tests/integration/test_copy_register_v2_workflow_http.py`.
- **`ImgCockpitPage.tsx`** → explicitly *"unrouted/deactivated → redirected to Poster Builder"* (`60d6b1c` body).
- **`BulkAngleSuggestionsPanel` / copy-components add-angles** → explicitly **removed as dead UI** — the commit states it *"has NO V2 endpoint equivalent … REMOVE_DEAD_UI."* This one is a pure removal with no successor, which is why the umbrella verdict is *superseded/removed* rather than *renamed*.

Governing decision record (live in repo): **`.ai/decisions/ADR-011-copy-register-v2-only-canonical-cutover.md`** — *Status: Accepted, Date: 2026-08-14, Owner authorization: explicit operator direction.* Decision §4: *"Active UI and API surfaces do not list, select, rotate, recommend, approve, mutate, or bind legacy copy rows."* §5: legacy endpoints return **HTTP 410 `LEGACY_COPY_STORAGE_DISABLED`**. Legacy **row data** was preserved as immutable receipts (not destroyed); the legacy **source files** audited here were removed. This matches the local project memory of "Legacy copy_set retirement — Task C #802→#809."

---

## C. Searches run that returned NOTHING (negative-result trust)

So a reviewer can trust the "zero orphaned" result is not a missed search:

1. **`git cat-file -e HEAD:<path>`** for all 45 → **0 present** on current branch.
2. **`git cat-file -e origin/main:<path>`** for all 45 → **0 present** on `main`.
3. **Silent-move sweep** — `git ls-tree -r --name-only HEAD` grepped for all 45 basenames → **no audited path survives under any other directory.** Two *same-basename but different* files exist and were checked as **distinct survivors, NOT relocations** of audited files:
   - `dashboard/src/pages/OperatorPage.rpaSelectors.component.test.tsx` — different path/scope from the deleted `dashboard/src/components/workspace/rpaSelectors.component.test.tsx`.
   - `dashboard/src/types/posterCopyRecommendations.ts` — a **types** module, different from the deleted **api** client `dashboard/src/api/posterCopyRecommendations.ts`.
4. **Content-identity membership** — `git hash-object` of each of the 45 snapshot files checked against every historical blob of that path on `main` lineage → **0 `NO_MATCH` (45/45 matched)**. No snapshot file contains content that never existed in git.
5. **Post-deletion re-add check** — no audited path reappears on `HEAD`/`origin/main` after 2026-08-19 (all remain `D`).

Methods used to reach each verdict: `git log --all --full-history -- <path>` (759 branches), `git diff-tree --name-status` deletion sets, `git merge-base --is-ancestor`, `git log --merges --ancestry-path`, GitHub `commits/{sha}/pulls` API, `git ls-tree` basename grep, and `git hash-object` blob-membership.

---

## D. Recommendation

1. **Let the cleanup proceed — `_ref_flowkit-official-visual` is safe to delete.** Every one of its 45 unique-looking files is an **intentionally retired legacy copy-storage artifact**, removed from `main` under owner-authorized **ADR-011** via merged **PRs #808 and #809**, and the snapshot's content is **byte-for-byte recoverable** from git history at the ADD/DEL SHAs above.
2. **No file needs recovery or reintegration.** There is **no P0 orphaned work**. Reintroducing any of these files would *re-create the exact defect the retirement closed* (competing legacy copy authority; HTTP 410 `LEGACY_COPY_STORAGE_DISABLED`).
3. **If the owner wants a permanent recovery pointer** instead of the folder: the complete pre-deletion tree is `git checkout 60d6b1c^ -- <path>` (frontend) / `b6fc722^` or `daf3dc3^` (tests) — no need to keep the on-disk snapshot for safety.

*Audit complete: proof matrix has a cited verdict for all 45 files. Read-only — no repo file under audit was modified, moved, or committed. This report is uncommitted.*
