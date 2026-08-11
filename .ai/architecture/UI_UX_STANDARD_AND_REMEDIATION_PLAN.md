# UI/UX Standard & Remediation Plan (BOSMAX Dashboard)

Status: DRAFT (Phase 0 — Foundation). Owner-gated. Read this before any dashboard
UI change. This is the SEQUENCE authority for the UI/UX cleanup workstream.

Scope: `dashboard/src` only. Generation lanes, extension, and backend generation
paths remain governed by `.ai/status/CURRENT_STATE.md` + ADR-007 and are NOT
touched by cosmetic work here.

---

## 1. Root cause (why it keeps happening)

The dashboard grew as a *developer/operator harness*: each capability shipped as a
full-page monolith, while the design system and navigation never caught up.

Hard evidence:
- Shared UI kit `components/ui` (7 primitives) imported by only **10 / 135** files
  → ~93% bespoke Tailwind.
- Two design systems coexist, neither fully adopted: `components/ui` (older) and
  the V4 `components/workflow` shell (newer, good).
- God-pages: `ProductsSalesAnalyzerPage` 5,253 LOC / 57 useState;
  `OperatorPage` 4,496 LOC (5 modes + 2 UIs); `AvatarRegistryPage` 2,533 LOC.
- Engine metadata leaked to operators (UUIDs, fingerprints, `claim_tokens_json`,
  WPS block-chains, `JSON.stringify` dumps, ticket codes like `M-03`/`ADR-008`).
- No shared registry pattern → CRUD is uneven and inconsistent across pages.
- 42 sidebar items; overlapping surfaces (3× IMG, 4× production); orphaned routes.

---

## 2. The Standard (canonical patterns — copy these, do not invent new ones)

**Reference implementations already in the repo (the templates):**
| Concern | Canonical template | Why |
|---|---|---|
| Guided generation lane | `pages/FacelessVideoPage.tsx` | Clean 5-step WorkflowStep flow; JSON only in debug drawer |
| Entity edit page | `pages/ProductDetailPage.tsx` | Tidy tabbed IA; advanced fields in `<details>` |
| Registry (full CRUD) | `pages/CopySetRegistryPage.tsx` | Only page fully on the `ui` kit + `ConfirmActionModal` |
| Layout shell | `components/workflow/*` (V4) | WorkflowStep / OperatorCockpit / ResolvedChip |
| Primitives | `components/ui/*` | Section, DataTable, FormField, Badge, ConfirmActionModal, HelperText |

**Rules (mandatory for any new/edited dashboard page):**
1. **Use the kit.** New tables → `DataTable`; new forms → `FormField`; sections →
   `Section`; destructive actions → `ConfirmActionModal` (never `window.confirm`).
2. **Hide engine metadata.** Raw UUIDs, fingerprints, JSON blobs, telemetry stages,
   ticket/endpoint strings, model engine aliases → inside a `<details>`
   "Technical details" drawer, never on the primary surface. Human labels + dates
   on the surface.
3. **Progressive disclosure.** Guided step order (1→N) or tabs; never a wall of
   always-open sections. Primary action reachable without scrolling past internals.
4. **CRUD completeness.** Every registry/entity surface must offer Create / Read /
   Update / Delete (soft-delete/archive acceptable) unless there is a documented
   reason it cannot.
5. **One surface per job.** No new page that duplicates an existing lane.

---

## 3. CRUD matrix — current vs target

| Registry | C | R | U | D | Gap → action | Backend status |
|---|:-:|:-:|:-:|:-:|---|---|
| CopySet | ✅ | ✅ | ✅ | ✅ | reference standard | ok |
| Avatar | ✅ | ✅ | ❌ | ✅ | add **edit** | verify `patch` route |
| SceneContext | ⚠️ | ✅ | ❌ | ✅ | add plain **add/edit** (not only promotion) | verify |
| ProductType | ✅ | ✅ | ❌ | ❌ | add **edit + delete** | **needs new routes** (none found in `agent/api`) |
| Asset | ❌ | ✅ | ❌ | ❌ | wire UI to existing mutations | `creative_assets.py` has `patch`/`archive`/`unarchive` (scattered) |

---

## 4. The Sequence (execute in this order — dependency-first, risk-ascending)

### Phase 0 — Foundation  ← THIS DOCUMENT
Lock the standard + templates + sequence. Additive, zero runtime risk. **DONE when
this file is accepted.**

### Phase 1 — Declutter (subtractive, low risk)  ← DONE (2026-08-10)
- [x] Deleted dead modules `components/workspace/{T2V,F2V,I2V}Module.tsx` + their
      `.test.tsx` (verified: no live imports). Removed dead `vi.mock` refs to them
      from the 4 `OperatorPage.*.component.test.tsx` files (kept live `IMGModule`).
- [x] Deleted orphaned `RpaProductionStudioPage` (`/rpa-production-studio`) + its
      test; removed its import + route from `App.tsx` (unreachable, duplicated P6;
      git retains history).
- [x] Exposed `/products` (main catalog) in the sidebar nav ("Product Catalog").
- [x] DEFERRED (as planned): removing the `classic` OperatorPage branch — it is the
      sanctioned PR#653 rollback. Revisit in Phase 5 after V4 is fully proven.
- Gate result: `npm run build` CLEAN (tsc -b + vite, 2496 modules). vitest 519/520;
      the 1 fail = `CreativeProductionStudioPage.test.tsx` 5s **timeout under full-suite
      load** (untouched file, zero shared imports) — passes 13/13 in isolation → flaky,
      not caused by this change. NOTE: `dashboard/node_modules` was empty → ran
      `npm ci` first (build/test cannot run otherwise).

### Phase 2 — Registry consistency + CRUD  (IN PROGRESS)
- [x] **ProductType CRUD (2026-08-10):** the clearest missing-CRUD gap, closed
      end-to-end. Backend: `crud.py` update/delete entry; service
      `update_product_strategy_type` / `delete_product_strategy_type` +
      `ProductStrategyTaxonomyNotFound`; API `PATCH`/`DELETE`
      `/product-strategy-type-registry/{cluster}/{product_type_group}`
      (404 not-found, 409 seed-guard — `SYSTEM_SEED` rows protected). FE:
      `products.ts` update/delete clients, `ProductStrategyTypeUpdateRequest`,
      and per-row Edit/Delete on `ProductTypeRegistryPage` (edit modal +
      `ConfirmActionModal` type-to-confirm; delete disabled for `SYSTEM_SEED`).
      Gate: build GREEN; vitest ProductType 11/11; backend registry API 10/10
      (incl. new PATCH/DELETE wiring, 404/409 mapping, real crud round-trip).
- Approach note: **surgical CRUD per registry first**, then extract the shared
  `RegistryShell` once a 2nd registry shares the pattern (avoids premature
  abstraction; lockdown = surgical).
- [ ] Asset: wire UI to existing `creative_assets` patch/archive (backend exists).
- [ ] Avatar / Scene: add edit (Avatar is C/R/D; Scene create is promotion-only).
- [ ] Extract `RegistryShell` (DataTable + Section + FormField + ConfirmActionModal)
      modeled on CopySet, then migrate the registries onto it.

### Phase 3 — Metadata hygiene (cross-cutting)
- Apply Rule #2 everywhere: move UUIDs/fingerprints/JSON/ticket codes into
  `<details>` drawers. Worst offenders first: OperatorPage classic view,
  MontagePage, ImgFastlane/ImgCockpit, the two ReviewDraft panels.

### Phase 4 — Information architecture
- Trim the 42-item sidebar; group by task, not by page.
- Consolidate the 3 IMG surfaces (OperatorPage IMG / ImgCockpit / ImgFastlane) → 1.
- Clarify Production Queue vs Production Studio (P6) vs RPA Queue Control roles.

### Phase 5 — God-page decomposition (highest risk, last)
- `ProductsSalesAnalyzerPage`: split into routed list (DataTable) + `/product/:id`
  editor (already clean); delete in-page detail pane.
- `OperatorPage`: retire classic branch (after Phase 1 defer clears), compose V4.
- The two 2,900-LOC ReviewDraft panels: stepper/accordion + sticky commit footer.

---

## 5. Governance
- Surgical per phase. No phase starts before the previous is accepted (owner gate).
- Each code phase: real `npm run build` + `scripts/verify-gate.ps1` before "green".
- `mandor-check` owned_paths: ensure `.ai/architecture/` + touched dashboard paths
  are in `docs/MODULE_STATUS.yaml` owned_paths before committing.
- No credit-spending generation is involved in any phase of this plan.
