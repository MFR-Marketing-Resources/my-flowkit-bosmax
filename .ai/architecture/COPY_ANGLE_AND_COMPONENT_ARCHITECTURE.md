# Copy Angle + Component Architecture

Status: **Phases A, B1, B2, C1, C2 BUILT AND MERGED** (PRs #457, #458, #459,
#460, #461). Phase D (mass generation) deliberately NOT started — the component
pool is still empty, so there is nothing to compose from yet.
Author: Claude Code. Date: 2026-07-24.

**Build order deviates from §6 on purpose: C1 (composer) comes BEFORE B2
(component authoring).** The composer is the CONSUMER that defines the contract
components must satisfy, and it costs zero tokens to build and test against
synthetic components. Authoring first would spend tokens against a guessed
spec. This was not theoretical — designing C1 immediately exposed that B1's
first draft used a `BODY` component type while `CopySetResponse` has no `body`
slot at all (its slots are angle/hook/subhook/usp_set/cta). Every authored BODY
component, and the tokens spent on it, would have been waste. Fixed before any
authoring ran.
Scope: the copywriting generation lane only. Does not touch the ADR-007
generation door, the negotiation brain, or any locked video path.

---

## 1. The problem, in evidence

The owner asked: *"how do we produce thousands of copies for ONE product?"*
and *"why is every MWTCB copy about a baby crying at night?"*

Measured on the live DB (read-only), 2026-07-24:

| Evidence | Value |
|---|---|
| Copy sets for MWTCB | 58 |
| Sets whose theme is `anak` | **57 / 58** |
| Sets mentioning `kembung` | 53 |
| Sets mentioning `sengal` (use-case #2) | 13 |
| Sets mentioning `gigitan/serangga` (use-case #4) | **4** |
| `subhook` distinct / total | **58 / 58** (zero component reuse) |
| Hooks appearing in >1 copy set, whole table | **6** |
| APPROVED product-intelligence snapshots | 30 |
| **Distinct angle sets across those 30 products** | **7 — all generic family templates** |
| Products whose angles derive from their own persona | **0** |

MWTCB (a traditional herbal oil for infant colic) currently shares an
**identical** angle list with a hair clipper, a lip tint and a cushion
foundation: `routine_upgrade, polished_finish, portable_touch_up,
confidence_boost, daily_convenience`.

The monoculture is not a bad batch. It is catalog-wide.

## 2. What ALREADY exists — do not rebuild

This section exists to prevent a parallel structure (repo law #257:
*"reuses copy_set — NO parallel DB"*).

| Capability | Where | State |
|---|---|---|
| Per-product angle storage | `product_intelligence_snapshot.copy_strategy_summary_json` → `{"angles": [...]}` | **EXISTS**, versioned, approved |
| Angle read precedence | `copy_grounding_service.py:168` — snapshot first, family fallback | **CORRECT** |
| Angle rotation across a batch | `ai_copy_assist_service._rotation_angles` + `angles[i % len(angles)]` | **CORRECT** |
| Per-candidate angle injection | brief fields `target_angle_strategy`, `available_angle_strategies` | **CORRECT** |
| Product persona (pains/desires/fears/triggers) | `product_intelligence_snapshot.buyer_persona_snapshot_json` | **EXISTS**, approved, product-specific |
| Formula registry (PAS/AIDA/HSO/BAB/PASTOR/PESTA) | `agent/authority/copy_formula_registry.py` | **EXISTS**, 6 canonical |
| Script reuse w/ LRU rotation + cap | `copy_rotation_service` (`REUSE_CAP = 15`) | **EXISTS**, deterministic |
| Text dedupe + near-dup similarity | `dedupe_key`, SCAN NEAR-DUP | **EXISTS** |
| Combination uniqueness ledger | `content_combination` (script × avatar × scene) | **EXISTS** |

**Conclusion: the angle plumbing is already correct end-to-end.** Nothing in
the read path needs changing.

## 3. Root cause

`copy_strategy_summary_json` is a **pass-through** field
(`product_intelligence_review_draft_service.py:496` stores whatever the payload
supplies). **No code anywhere derives angles from the product's own persona.**
So every draft inherited the framework family template, and every approved
snapshot froze it.

Two consequences:

1. The rotation axis is real but **irrelevant to the product**. The LLM is handed
   `polished_finish` for a colic oil, cannot use it, and falls back to the single
   most vivid pain in the persona → the crying baby, every time.
2. `product.section_6_copy_hint` carries the same boilerplate
   (*"Angle: Trust-led beauty and personal care benefits"*), so the contamination
   reaches the **video** compiler, not only copy.

## 4. Why the current model can never reach thousands

`copy_set` is a **frozen bundle**: angle+hook+subhook+usp_set+cta in one row,
minted whole by one LLM call.

```
variations = number of LLM calls          (linear, forever)
```

Worse, diversity *collapses* as N grows on one product — empirically 58 sets
produced ~1 real theme. 1,000 sets on this model is not 1,000 contents; it is a
handful of themes reworded 200× each, which the near-dup scanner will flag.

## 5. Target model

Compose **within an angle** (a hook about infant colic must never pair with a
body about post-work body aches):

```
total = formulas × Σ_angle ( hooks_a × subhooks_a × usp_sets_a × ctas_a )
```

Worked example for MWTCB's four real use-cases (colic / body aches / numbness /
insect bites):

| Authored components | Count |
|---|---|
| 4 angles × 8 hooks | 32 |
| 4 angles × 5 subhooks | 20 |
| 4 angles × 4 usp_sets | 16 |
| CTAs | 5 |
| **Total authored** | **73** |

`8×5×4×5 = 800` per angle × 4 angles = **3,200** × 6 formulas ≈ **19,200**
valid combinations from **73 authored pieces**.

The LLM is still used — but to **author components** (e.g. "write 8 hooks for
angle=insect-bite"), never to mint whole sets.

## 6. Phased plan

Angle is the key components are organised by. Building the pool or the composer
before angles are correct means building on sand. Order is therefore fixed.

### Phase A — Angle truth (prerequisite)

| Round | Work | Notes |
|---|---|---|
| **A1** | Deterministic `derive_angles(persona, product)` — pure function, no LLM. Source: approved `buyer_persona_snapshot_json` pains/desires/triggers. Fail-closed: no persona → no derived angles → family fallback (today's behaviour, unchanged). | New pure module + unit tests. Touches no existing read path. |
| **A2** | Wire the derivation into draft creation so new snapshots get product-specific angles instead of the family template. Family list remains the documented fallback. | Single write-path change. |
| **A3** | Repair the 30 legacy approved products. **Implemented differently from this row's original plan** — see below. | No mutation at all. |

**A3 as built (deviation, deliberate).** The original plan was to regenerate 27
snapshots as v3 drafts for owner approval. That was rejected on two grounds: it
would take 27 manual approvals, and it is unnecessary. Approved snapshots are
immutable, so the repair happens at READ time in `copy_grounding_service`:

1. angles stamped `angle_source=DERIVED_FROM_APPROVED_PERSONA` (written by A2) — trusted;
2. stored angles that are **not** verbatim a framework family template — a deliberate choice, respected;
3. otherwise derive live from **this snapshot's own approved persona** — the derivation source is already approved data, so nothing unreviewed enters the pipeline;
4. otherwise stored angles / framework fallback (unchanged behaviour).

The family-template match is **exact**, never fuzzy, so an authored angle list
can never be mistaken for contamination. Measured on live data: **29 of 30
snapshots repaired, 1 unchanged, distinct angle sets 7 → 29, zero rows written.**

**Also in A:** clear the beauty boilerplate out of `product.section_6_copy_hint`
so the video compiler stops inheriting it.

### Phase B — Component pool

| Round | Work |
|---|---|
| **B1** | ✅ **BUILT** — new `copy_component` table keyed by `(product_id, angle_key, component_type)` + `pool_capacity()` math. See the storage decision below. |

**B1 storage decision (this doc's earlier recommendation was WRONG).** Section 9
originally recommended extending `copy_intelligence_seed` to honour law #257.
On inspecting its actual shape that is a category error:

* every seed row bundles `hook_script` + `body_script` + `cta_script` **together**
  — the exact monolithic shape that makes `copy_set` unable to scale;
* it carries Kalodata import provenance (`source_workbook`/`source_sheet`/`source_row`)
  meaningless for authored components;
* it holds 420 imported **competitor ads** (research), and mixing authored
  building blocks into that corpus pollutes both.

Law #257 forbids a *parallel store of an existing concept*. An atomic component
— ONE hook, or ONE body — is a concept **no existing table holds**: `copy_set`
stores assembled copies, `copy_intelligence_seed` stores whole competitor ads.
So `copy_component` is a new concept, not a duplicate, and the law is honoured.
| **B2** | LLM component authoring: N components for ONE angle per call, claim-scanned individually, landing `REVIEW_REQUIRED` (never auto-approved — existing law). |

### Phase C — Composer + coverage

| Round | Work |
|---|---|
| **C1** | Deterministic composer assembling `copy_set` rows from components, reusing the `copy_rotation_service` LRU pattern. Output still flows through the existing dedupe / near-dup / `content_combination` gates unchanged. |
| **C2** | ✅ **BUILT** — `copy_coverage_service`, wired into every composition and exposed at `GET /api/copy-components/coverage/{id}`. |

**C2 threshold design (changed during build).** The plan said "warn above ~35%".
An ABSOLUTE bar turned out to be wrong for small angle counts: with 2 angles the
dominant share can never drop below 0.50, so a fixed 0.35 bar would flag every
2-angle product forever — a permanent false alarm. Bars are therefore RELATIVE
to the even split (1/n), capped so a large angle count cannot make them
meaningless: skew above `even × 1.4` (cap 0.60), monoculture above `even × 2.4`
(cap 0.90). For MWTCB's 4 angles that reproduces the intended 0.35 / 0.60
exactly. The two bars can never invert.

Coverage judges TWO axes, because either alone can be gamed: **concentration**
(the largest angle's share) and **breadth** (how many AVAILABLE angles appear at
all — a perfect 50/50 across 2 of 4 angles still ignores two real use-cases).
Advisory by default; `blocking=True` turns it into a hard gate.

### Phase D — Mass generation

Only after A–C. Not before.

## 7. Invariants that must survive

- **Claim safety is never weakened.** Components are claim-scanned individually
  *and* the composed output is re-scanned. MEDICAL_CLAIM stays fail-closed.
- **Never auto-approve.** The `APPROVAL_PHRASE` gate stays with the operator.
- **Approved snapshots are immutable.** Backfill = new version + approval.
- **No parallel DB.** Prefer extending existing tables.
- **`REUSE_CAP = 15`** and the `content_combination` uniqueness law are untouched.
- **Uniqueness ≠ diversity.** Both gates must exist; neither replaces the other.

## 8. Validation gates

- Phase A: unit tests on `derive_angles` (incl. empty/partial persona →
  fail-closed); `scripts/verify-gate.ps1`; a read-only report showing the
  angle set per product before/after.
- Phase B/C: component→composed claim-scan tests; a composition-count report;
  `scripts/verify-gate.ps1`.
- No live Google Flow and no credit burn anywhere in A–C.

## 9. Open decisions for the owner

1. **Angle granularity** — is an angle a *pain* (`perut kembung`), or a
   *pain × audience* pair (`perut kembung × ibu bapa` vs `sengal × pekerja`)?
   Recommendation: pain × audience, because the persona already differs per
   use-case and it doubles usable angles.
2. ~~**B1 storage** — extend `copy_intelligence_seed` or new `copy_component`
   table?~~ **RESOLVED: new `copy_component` table.** The extend recommendation
   was withdrawn after inspecting the seed table's real shape — see the B1
   storage decision in §6.
3. **A3 approval batching** — approve 30 regenerated snapshots one-by-one, or
   as one reviewed batch?
4. Do the 420 imported Kalodata seeds (all `NEEDS_REVIEW`, `body_script` 100%
   empty, bespoke per competitor product) get promoted into the component pool,
   or stay research-only? Recommendation: research-only — they are whole
   competitor ads, not reusable parts.

## 10. Explicitly NOT in scope

- The ADR-007 generation door, negotiation brain, retrieval, extend/concat.
- Video prompt compilation beyond clearing the contaminated
  `section_6_copy_hint` string.
- Poster copy (`poster_copy_set` is a separate lane).
