# 🛑 V4 UI OVERHAUL — BRANCH HANDOFF & DO-NOT-CLOBBER

**Read this before touching the dashboard UI, the sidebar nav, the StudioShell/
ResultsSidebar, or the Poster Builder. This is finished, intentional work parked
on a branch. Do not delete, revert, or blind-merge it.**

Last updated: 2026-08-11. Authoritative shared signal on GitHub = **PR #705**
(kept as *draft* on purpose). This file lives on the branch below; a session
working only on `main` will not auto-read it — use PR #705 as the cross-agent
source of truth and point new sessions at it.

---

## What is done (and where it lives)
- **Branch:** `fix/v4-ui-shell-and-f2v-avatar`
- **HEAD:** `9266f9a` — pushed to `origin` (safe on GitHub; local == remote).
- **PR:** #705 → `main` (DRAFT — see divergence warning below; do NOT click merge).
- **Runtime:** live-verified all session on the local `:8100` dev override.

The branch is the full **V4 UI overhaul** (41 commits on top of base `0016cb3`):
- Sidebar nav restructured into collapsible **task-groups**; latest reorg groups
  every generation lane as **VIDEO PRODUCTION** (t2v/hybrid/f2v/i2v/faceless/
  montage/production-studio) + **IMAGE PRODUCTION** (Image Gen/IMG Cockpit/IMG
  Fastlane/Poster Builder); old `PRODUCTION` → `PUBLISH & JOBS`.
- **StudioShell ResultsSidebar** rolled to all 9 generation lanes (session-scoped
  results, no cockpit overlap, English).
- Phase-B result panels (regenerate/save/delete), legacy-page purges, registry
  CRUD (ProductType/Avatar/Scene), metadata-hygiene `<details>` disclosures.
- **Poster Builder fully standardized Malay → English** (11 source files + 9
  synced test assertions). Full dashboard vitest **521/521 green**;
  `tsc -b && vite build` clean.

## ⚠️ DIVERGENCE — do NOT merge this branch onto `main`
`origin/main` has advanced **~100 commits** past this branch's base, on a
**different track** (poster-builder v3 #657–#675, workspace, faceless/montage,
cutout #693–#704 — a mix of `claude/*` and `codex/*` work). The two have
diverged hard:
- GitHub reports PR #705 **CONFLICTING / DIRTY**, diff **+4,579 / −15,140**.
  A branch→main merge would **delete ~15k lines of newer production work.**
- `main`'s `PosterGuidedShell.tsx` is **+703 lines different and still Malay**;
  `main` never adopted the task-group nav at all.

**The golden rule here: bring `main` INTO the branch — never merge this stale
branch onto `main`.**

## 🚫 Do NOT
- Do **not** merge PR #705 as-is (it reverts newer work; GitHub already blocks it).
- Do **not** force-push over, delete, or "garbage-collect" `fix/v4-ui-shell-and-f2v-avatar`.
- Do **not** treat these dashboard/poster/nav files as stale and "clean them up."
- Do **not** hand-serve the branch onto the canonical `:8100` on boot (that
  re-introduces the dev-root bug that fix #700 deliberately closed).

## ✅ Runtime truth (so nothing looks "lost")
- Canonical `:8100` (Startup shortcut `BOSMAX Canonical Runtime`) serves **only a
  pinned, provenance-validated release** — currently `current → c7316ba`
  (= `origin/main` tip, PR #704). It **fails closed** on dev-root/dirty/mismatch.
- Therefore after any reboot, `:8100` = **latest official `main`** (clean,
  known-good), which does **not** include this branch's V4 UI. That is expected,
  not a regression — the V4 work is safe in git, just not merged.
- Data (`flow_agent.db`, `data/`) is external to the release and persists across
  reboots regardless of which code serves.

## 🔧 Correct reconciliation sequence (coordinated with Codex, clean tree)
1. Codex commits/pushes its current uncommitted WIP (product-intelligence /
   taxonomy) so the tree is clean and its work is safe.
2. On a clean tree, on this branch: `git merge origin/main` (bring main IN —
   merge, not rebase; the branch history carries merges).
3. Resolve per file: on files `main` actively developed (poster-builder,
   workspace, cutout) **main wins**, then re-apply the V4 layer (i18n,
   ResultsSidebar, nav) on top; on pure V4 inventions (nav task-groups,
   `ResultsSidebar.tsx`) the branch wins.
4. Full gate: `npm run build` + full vitest + backend pytest smoke + mandor-check.
5. Re-validate on `:8100`.
6. Then merge the reconciled branch → `main` → deploy a canonical release
   (`deploy-canonical-release.ps1 -Sha <origin/main>`).

## Not mine — do not sweep
While this work was committed, a co-tenant Codex session had **heavy uncommitted
WIP** in the working tree (`agent/*` product-intelligence & taxonomy,
ProductRegistration / ProductTypeRegistry, `dashboard/src/types/index.ts`,
untracked `.codex/` `.hermes/` and new API files). My commit `9266f9a` staged
**only** the 15 Poster + `App.tsx` files by explicit path. Leave the co-tenant
WIP alone.
