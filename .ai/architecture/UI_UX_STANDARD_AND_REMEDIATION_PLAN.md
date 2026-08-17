# UI/UX Standard & Remediation Plan (BOSMAX Dashboard)

Status: CANONICAL (Creator Workflow UX Standard in Force; Dashboard Remediation Roadmap Active). Owner-gated. Read this before any dashboard
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

## 2. General BOSMAX UI/UX Standard (Canonical Patterns & Rules)

**Reference implementations already in the repo (the templates):**
| Concern | Canonical template | Why |
|---|---|---|
| Guided generation lane | `pages/FacelessVideoPage.tsx` | Clean 5-step WorkflowStep flow; JSON only in debug drawer |
| Entity edit page | `pages/ProductDetailPage.tsx` | Tidy tabbed IA; advanced fields in `<details>` |
| Registry (full CRUD) | `pages/CopySetRegistryPage.tsx` | Only page fully on the `ui` kit + `ConfirmActionModal` |
| Layout shell | `components/workflow/*` (V4) | WorkflowStep / OperatorCockpit / ResolvedChip |
| Primitives | `components/ui/*` | Section, DataTable, FormField, Badge, ConfirmActionModal, HelperText, TechnicalDetails |

**General Rules (mandatory for any new/edited dashboard page):**
1. **Use the kit.** New tables → `DataTable`; new forms → `FormField`; sections →
   `Section`; destructive actions → `ConfirmActionModal` (never `window.confirm`).
2. **Hide engine metadata.** Raw UUIDs, fingerprints, JSON blobs, telemetry stages,
   ticket/endpoint strings, model engine aliases → inside a `<details>`
   "Technical details" drawer (`<TechnicalDetails>`), never on the primary surface. Human labels + dates
   on the surface.
3. **Progressive disclosure.** Guided step order (1→N) or tabs; never a wall of
   always-open sections. Primary action reachable without scrolling past internals.
4. **CRUD completeness.** Every registry/entity surface must offer Create / Read /
   Update / Delete (soft-delete/archive acceptable) unless there is a documented
   reason it cannot.
5. **One surface per job.** No new page that duplicates an existing lane.

---

## 3. CREATOR WORKFLOW UX CONTRACT (Enforceable Standard)

All active video and image creator surfaces (`OperatorPage`, `FacelessVideoPage`, `MontagePage`, `PosterBuilderPage`, `CreativeProductionStudioPage`, etc.) must inherit and strictly comply with the following 10 canonical rules:

### 1. Canonical Progressive Workflow Grammar
Every creation surface follows a standardized 6-step progressive workflow shell:
- **01 Product**: Select product via `SearchableProductSelect`.
- **02 Copywriting**: Select approved copy or generate draft via canonical `CopywritingSourceSelector`.
- **03 Creative / Scene Settings**: Presenter, Hook Strategy, Background, Scene Direction.
- **04 Media / Generation Settings**: Model selection, Aspect Ratio, Resolution, Duration.
- **05 Review & Prepare**: Credit-free validation, prompt compilation, and blocker checks.
- **06 Generate**: Operator-gated generation (credits spent only here).

### 2. Default-Surface Metadata Ban
Normal user surfaces must NEVER display raw technical metadata:
- Forbidden on default view: Blueprint IDs, Revision IDs, Formula IDs, Universal adapter names, `COPY_REQUIRED` / `COPY_NOT_REQUIRED`, raw product UUIDs, authority fingerprints, SHA256 digests, semantic review codes, WPS block indices, backend blocker codes (e.g. `APPROVED_COPY_CAPACITY_SHORTFALL`), or raw telemetry JSON.
- Allowed on default view: Human product title, Angle label, Hook / Body / CTA preview, status badges ("Approved", "Needs Approval", "Active"), model display labels, duration in seconds, and stable human-actionable blocker messages ("Copywriting needs attention. Open Copy Register to select or approve copy.").

### 3. Machine State vs Human Presentation Rule
Preserve all underlying V2 authority checks, readiness gates, lineages, and telemetry internally; only remove internal jargon from default visual presentation. All `data-testid` elements required by testing harnesses remain accessible inside diagnostic wrappers.

### 4. Shared Copywriting Selection Contract & Multi-Product Cohort Rule
- **Single-Product Creator Lanes** (`OperatorPage`, `FacelessVideoPage`, `MontagePage`, `PosterBuilderPage`):
  Must embed the canonical `CopywritingSourceSelector` in Step 2, providing two distinct choices:
  - **Choice 1: AI Copy Assistant** (Strategy/Formula selector → Angle generation → Draft copy generation with review handoff).
  - **Choice 2: Copy Register** (Angle filter → Paginated copy sets with Angle/Hook/Body/CTA → "Use This Copy" activation).
- **Multi-Product Cohort Exception (Production Studio P6 & Production Queue)**:
  Production Studio operates over multi-product cohorts (e.g. 5–20 products concurrently). Embedding full interactive authoring selectors for every product in a cohort list would cause severe layout fragmentation. Therefore, multi-product cohort surfaces use the concise `CopyArchitectureV2LaneCard` per allocated product. This displays human-readable status ("Copy Ready" vs "Copywriting Required") and an actionable `"Open Copy Register ↗"` deep link per blocked product, with all technical authority metadata kept within `<TechnicalDetails>`.

### 5. Explicit No-Auto-Approval Rule (Zero Client-Side Fabrication)
- **Selection is NOT Approval**: "Use This Copy" is an activation action for approved copy. It MUST NEVER auto-approve a `DRAFT` or non-production-valid blueprint.
- **No Fabricated Review Booleans**: Client-side UI code must never fabricate `semantic_review: { decision: "APPROVED" }` or fake `readiness_proof` flags (`readiness_validated`, `safety_validated`, etc.).
- **Draft Copy Guidance**: If a blueprint is in `DRAFT` status or generated via the AI Assistant, the selector must clearly render a `"Needs Approval"` badge and provide a direct review link (`/creative/copy-registry?product_id=...&blueprint_id=...`) to the governed review workflow.

### 6. Canonical Product-Global Activation Semantics
- In BOSMAX Copy Architecture V2, copy blueprint activation via `/api/copy-register/v2/blueprints/{blueprint_id}/activate` is **PRODUCT-GLOBAL** across all 8 copy-required creator lanes (`POSTER_BUILDER`, `T2V`, `F2V`, `I2V`, `HYBRID`, `MONTAGE`, `FACELESS`, `PRODUCTION_STUDIO_P6`).
- When an approved blueprint is activated, it atomically binds as the active copy for that product across all creator lanes.
- The UI must be semantically truthful: do not imply per-lane independent copy selection when activation is product-global.

### 7. Copy Generator vs Copy Library Separation
The Copy Register (`CopySetRegistryPage.tsx`) is separated into two dedicated top-level tabs:
- **Copy Generator**: Guided authoring wizard (Product → Truth Proof → Formula & Angle → Generation & Governance Approval).
- **Copy Library**: Searchable, filterable by Angle, paginated Hook/Body/CTA cards with activation status.

### 8. TechnicalDetails Owner/Debug Disclosure Rule
All diagnostics, IDs, digests, lineages, and telemetry must reside within the reusable `<TechnicalDetails title="Technical details">` drawer primitive, keeping the default UI clean while allowing operators and automated tests full inspection capability.

### 9. Required Regression Tests for Creator Surfaces
Any new or modified creator surface must include regression tests asserting:
- Absence of forbidden technical codes on default visual presentation.
- Inability to auto-approve or activate unapproved drafts.
- Proper handling of empty, draft, and approved copy states.
- Credit-safety: zero provider calls during preparation/setup.

### 10. Reusable Primitives Requirement
New creation surfaces must reuse established primitives (`WorkflowStep`, `TechnicalDetails`, `CopywritingSourceSelector`, `SearchableProductSelect`, `ResolvedChip`) instead of creating bespoke page-level copies.

---

## 4. Active Creator Lane Coverage Matrix

| Route | Page / Component | Status | Copy Policy | Uses WorkflowStep | Uses CopywritingSourceSelector | Technical Leaks Removed |
|---|---|---|---|---|---|---|
| `/operator/hybrid` | `OperatorPage.tsx` | Active | REQUIRED | Yes | Yes (Step 2) | Yes (leaks inside `<TechnicalDetails>`) |
| `/operator/t2v` | Redirects to `/operator/hybrid` | Deactivated (ADR-007) | N/A | N/A | N/A | N/A |
| `/operator/f2v` | Redirects to `/operator/hybrid` | Deactivated (ADR-007) | N/A | N/A | N/A | N/A |
| `/operator/i2v` | Redirects to `/operator/hybrid` | Deactivated (ADR-007) | N/A | N/A | N/A | N/A |
| `/operator/faceless` | `FacelessVideoPage.tsx` | Active | REQUIRED | Yes | Yes (Step 2) | Yes |
| `/operator/montage` | `MontagePage.tsx` | Active | REQUIRED | Yes | Yes (Step 2) | Yes |
| `/creative/poster-builder` | `PosterBuilderPage.tsx` | Active | REQUIRED | Yes | Yes (Step 2) | Yes |
| `/production-studio` | `CreativeProductionStudioPage.tsx` | Active | REQUIRED | Yes (P6) | Authority Card (Cohort) | Yes |
| `/production-queue` | `ProductionQueuePage.tsx` | Active | Queue Execution | Standard Table | Authority Card (Cohort) | Yes |
| `/creative/copy-registry` | `CopySetRegistryPage.tsx` | Active | Authoring / Library | Yes (Generator) | Source of Truth | Yes (2 Tabs) |
| `/operator/img` | Redirects to `/creative/poster-builder` | Deactivated | N/A | N/A | N/A | N/A |
| `/assets/img-cockpit` | Redirects to `/creative/poster-builder` | Deactivated | N/A | N/A | N/A | N/A |
| `/assets/img-fastlane` | Redirects to `/creative/poster-builder` | Deactivated | N/A | N/A | N/A | N/A |

---

## 5. CRUD Matrix — Current vs Target

| Registry | C | R | U | D | Gap → action | Backend status |
|---|:-:|:-:|:-:|:-:|---|---|
| CopySet | ✅ | ✅ | ✅ | ✅ | reference standard | ok |
| Avatar | ✅ | ✅ | ❌ | ✅ | add **edit** | verify `patch` route |
| SceneContext | ⚠️ | ✅ | ❌ | ✅ | add plain **add/edit** (not only promotion) | verify |
| ProductType | ✅ | ✅ | ❌ | ❌ | add **edit + delete** | **needs new routes** (none found in `agent/api`) |
| Asset | ❌ | ✅ | ❌ | ❌ | wire UI to existing mutations | `creative_assets.py` has `patch`/`archive`/`unarchive` (scattered) |

---

## 6. Dashboard UI/UX Remediation Sequence (Active Roadmap)

### Phase 0 — Foundation  ← COMPLETE
Lock the standard + templates + sequence. Additive, zero runtime risk.

### Phase 1 — Declutter (subtractive, low risk)  ← COMPLETE (2026-08-10)
- [x] Deleted dead modules `components/workspace/{T2V,F2V,I2V}Module.tsx` + their
      `.test.tsx` (verified: no live imports). Removed dead `vi.mock` refs to them
      from the 4 `OperatorPage.*.component.test.tsx` files (kept live `IMGModule`).
- [x] Deleted orphaned `RpaProductionStudioPage` (`/rpa-production-studio`) + its
      test; removed its import + route from `App.tsx` (unreachable, duplicated P6;
      git retains history).
- [x] Exposed `/products` (main catalog) in the sidebar nav ("Product Catalog").
- [x] DEFERRED (as planned): removing the `classic` OperatorPage branch — it is the
      sanctioned PR#653 rollback. Revisit in Phase 5 after V4 is fully proven.
- Gate result: `npm run build` CLEAN (tsc -b + vite, 2496 modules).

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
- [ ] Asset: wire UI to existing `creative_assets` patch/archive (backend exists).
- [ ] Avatar / Scene: add edit (Avatar is C/R/D; Scene create is promotion-only).
- [ ] Extract `RegistryShell` (DataTable + Section + FormField + ConfirmActionModal)
      modeled on CopySet, then migrate the registries onto it.

### Phase 3 — Metadata hygiene (cross-cutting)
- Apply Rule #2 everywhere: move UUIDs/fingerprints/JSON/ticket codes into
  `<details>` drawers (`<TechnicalDetails>`). Worst offenders: OperatorPage classic view,
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

## 7. Governance & Verification
- Strict lockdown in force: zero credit-spending generation during any test or build.
- Verification command: `cd dashboard && npm run verify` / `tsc -b && vite build` and `npx vitest run`.
- `mandor-check` owned_paths: ensure `.ai/architecture/` + touched dashboard paths
  are in `docs/MODULE_STATUS.yaml` owned_paths before committing.
