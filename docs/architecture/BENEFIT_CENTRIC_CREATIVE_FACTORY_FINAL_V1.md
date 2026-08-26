# Benefit-Centric Creative Factory — FINAL V1 (Rounds 1–3)

> **SYSTEM OWNS STRUCTURE · AI AUTHORS CREATIVE WORDS · VIDEO ENGINE OWNS VISUAL EXECUTION.**
>
> Round 3 extends the law: **SYSTEM ALSO OWNS VISUAL-VARIATION SELECTION,
> RECIPE LINEAGE, PROMPT SNAPSHOTS, and PRODUCTION ORCHESTRATION.**

**Status:** implemented · provider-free tests green · the only live touch is a
credit-bearing video dispatch, gated behind an operator confirmation phrase + a
human-approved execution-approval manifest.
**Arc:** Round 1 (Benefit-Centric Creative Factory, PR #913) → Round 2 (Benefit
On-Demand Copy Renderer, PR #917) → Round 3 (visual variations + execution
recipes + prompt snapshots + Production Studio; behavioral acceptance PR #924).
This document is the completed-system reference; the per-round docs
(`BENEFIT_CENTRIC_CREATIVE_FACTORY_V1.md`, `BENEFIT_ON_DEMAND_COPY_RENDERER_V1.md`)
remain the ground truth for R1/R2 internals.

---

## 1. The three-round arc

Round 1–3 replace the frozen **FAST54 / Storyboard-V3** single-route-anchor
authoring (one provider call carrying Product Truth + route + storyline +
evidence + hooks/body/CTA + WPS + duration + projection) with a decomposed,
mostly provider-free factory in which each authority owns exactly one thing.

```
R1  Product ─▶ Benefit Registry (Benefit REQUIRED + Usage Hint OPTIONAL)
      │ deterministic provider-free PI cross-check → VERIFIED/REVIEW_REQUIRED/BLOCKED
      │ one bounded STRUCTURE call → 3 Angles · 6 Hooks · 3 Bodies · 3 CTAs
      ▼ 54/angle → 162/benefit virtual (Hook×Body×CTA) recipes, fingerprinted
R2  VERIFIED benefit + duration + target ─▶ On-Demand rendered copy
      │ deterministic recipe selection (0 calls) → ONE STRUCTURE stitch call → ≤5
      │ lock / regenerate / finalize → immutable render-artifact CACHE
      ▼ BENEFIT_COPY_RENDER_V1 (request-scoped, honest, NOT a V2 binding)
      ▼ N create_workspace_execution_package = N READY prompt packages
R3  FINALIZED rendered copy + production recipe + AUTO visual variation
      │ deterministic visual resolver (0 calls) → N coherent visual identities
      │ CreativeExecutionRecipeV1 (immutable durable unit; exact-replay by digest)
      │ provider-free compile → immutable prompt snapshot (reuses the WEP)
      ▼ Production Studio / P6 batch orchestration → (live-only) provider payload
      ▼ rendered-output BEHAVIORAL acceptance (PR #924): PASS / FAIL / UNPROVEN
```

- **Round 1 — foundation.** Benefit Registry (`product_benefit`), deterministic
  PI verification (reuses `product_intelligence_snapshot_service`, the claim gate,
  and `copy_similarity_service`), Creative Atoms
  (`creative_angle`/`creative_hook`/`creative_body`/`creative_cta`), and
  compatible-recipe capacity (`creative_atom_compatibility`; empty ⇒ within-Angle
  Cartesian). The AI returns **only words**; BOSMAX assigns every id/digest/lineage.
- **Round 2 — on-demand rendered copy.** System owns selection/formula/duration/
  WPS/cache/idempotency; the AI only stitches Round-1 atom seeds into complete
  spoken scripts. A finalized candidate resolves to **`BENEFIT_COPY_RENDER_V1`**
  and materializes N **READY** prompt packages — no production, no video, no
  Copy-V2 binding write.
- **Round 3 — visuals, durable recipes, orchestration.** The completed layer this
  document specifies: deterministic visual variations, the durable
  `CreativeExecutionRecipeV1`, immutable prompt snapshots via package reuse, and
  the Production Studio (P6) provider-free plan lifecycle.

## 2. Authority boundaries — THE LAW

| Owner | Owns | Round-3 surface |
|---|---|---|
| **SYSTEM** | structure · **visual-variation selection** · **recipe lineage** · **prompt snapshots** · **production orchestration** | `auto_visual_variation_service`, `creative_execution_recipe_service`, `creative_production_*` |
| **AI** | creative **words** only (Round-1 atoms, Round-2 stitched dialogue) | (unchanged — no new copy call in R3) |
| **VIDEO ENGINE** | visual **execution** (pixels) | `flow_client` / `make_video` (unchanged) |

**No new provider is introduced in Round 3.** There is **no new copy LLM, no new
visual LLM, and no new prompt compiler**. The visual resolver composes existing
coherent visual authorities; the recipe compiler reuses the existing
`create_workspace_execution_package`. Everything from rendered copy through the
compiled prompt snapshot is **provider-free**; the sole credit-spending act is a
live video dispatch, and it is gated (§7, §10).

## 3. AUTO Visual Variation (`agent/services/auto_visual_variation_service.py`)

`resolve_visual_variations(product_id, production_recipe, count, *, avatar_id,
seed)` composes the **existing** coherent visual authorities into `count`
coherent, deterministically-spread visual configurations — **provider-free, no
random pick, no independent camera choice (camera follows scene)**. Version
constant `AUTO_VISUAL_RESOLVER_VERSION = "AUTO_VISUAL_VARIATION_V1"`. It reuses,
never duplicates:

- **HYBRID** (`_hybrid_pool`) → `creative_recipe_service.generate_product_recipes`
  (avatar × scene → **scene-derived camera**, `camera_preset_code`),
  `creative_recipe_service.resolve_recipe_descriptors` for the environment
  (`scene_template.setting`), and `avatar_registry.resolve_presenter` for
  **wardrobe** (descriptive only — never fails the pool). `character_presence =
  "VISIBLE_CREATOR"`. `review_required` ⇒ fail-closed `HYBRID_VISUAL_NOT_READY`; a
  governed `avatar_id` absent from the scene pool ⇒ `HYBRID_AVATAR_NOT_IN_POOL`.
- **FACELESS** (`_faceless_scene_pool`) → `faceless_lane_service.resolve_faceless_scene_authority(...
  variation_index=k)` enumerated over `_MAX_SCENE_PROBE = 64` with a
  two-full-cycle no-new-fingerprint stop. **No avatar** (`avatar_id = None`),
  `character_presence = "FACELESS"`. Empty ⇒ `FACELESS_SCENE_POOL_EMPTY`;
  strategy/product errors map to `FACELESS_SCENE_STRATEGY_REQUIRED` /
  `FACELESS_PRODUCT_NOT_FOUND`.
- **MONTAGE** (`_montage_pool`) → `product_mascot_service.get_current_product_mascot`
  supplies the **mascot identity as the fixed protagonist**
  (`montage_mascot_media_id`), consumed as a **CHARACTER_REFERENCE — never a human
  Avatar Registry presenter**. Scene choreography (the FACELESS lane) provides the
  beat variation; the mascot media id is folded into each fingerprint so **MONTAGE
  and FACELESS variations never collide**. No mascot ⇒ fail-closed
  `PRODUCT_MASCOT_KEY_VISUAL_REQUIRED`.

**Determinism.** `visual_variation_fingerprint(payload)` is a SHA-256 over only
the stable, provider-affecting visual identity (timestamps/uuids never included by
construction), so two visually equivalent variations fingerprint identically.
`_spread` performs a **seeded round-robin** (`_seed_offset` over
`AUTO_VISUAL_RESOLVER_VERSION|seed|product_id|production_recipe`): for `N` outputs
it selects `N` **distinct** fingerprints when capacity allows and only falls back
to **controlled, recorded reuse** (`reuse=True`, `reuse_reason =
VISUAL_CAPACITY_REUSE`) once `unique_capacity` is exhausted — never a silent
duplicate. The result reports `unique_capacity` and `controlled_reuse_count`.
Nothing here writes DB state or spends credits.

## 4. `CreativeExecutionRecipeV1` — the immutable durable unit

The recipe is the durable execution unit that binds, in one immutable row, the
**copy identity + production recipe + visual identity + duration + product-truth
lineage + system authority versions**.

**Contract** (`agent/models/creative_execution_recipe_v1.py`):
`RECIPE_SCHEMA_VERSION = "CREATIVE_EXECUTION_RECIPE_V1"`;
`CreateExecutionRecipesRequest` (`candidate_id`, `production_recipe`,
`visual_count` 1–50, `duration_seconds`, `avatar_id`, `treatment_id`, `seed`;
`extra="forbid"`) — **ONE finalized copy candidate → `visual_count` recipes = the
SAME immutable copy across distinct governed visuals (`SAME_SCRIPT_DIFF_VISUALS`)**.
`PRODUCTION_RECIPE_TO_COPY_LANE = {HYBRID:HYBRID, FACELESS:FACELESS,
MONTAGE:FACELESS}` — MONTAGE consumes **FACELESS-lane** rendered copy (the mascot
speaks the same presenter-free dialogue), so no new copy lane is introduced.

**Table** (`agent/db/schema.py → CREATIVE_EXECUTION_RECIPE_SCHEMA`,
`creative_execution_recipe_v1`, additive only): `recipe_id` PK (`CER_<hex>`),
`recipe_identity_digest` **NOT NULL UNIQUE**, `production_recipe` CHECK
∈(HYBRID,FACELESS,MONTAGE); copy-identity columns (`copy_session_id`,
`candidate_id`, `artifact_id`, `copy_text_digest`, `copy_source`, `formula_id/
version`, `atom_recipe_fingerprint`, `angle/hook/body/cta_id`); duration
(`requested_total_duration_seconds`, `generation_mode`, `orchestration_digest`);
deterministic visual identity (`visual_variation_fingerprint`,
`visual_resolver_version`, `avatar_id`, `scene_template_id`, `camera_preset_code`,
`wardrobe`, `environment`, `treatment_id`, `faceless_actor_profile`,
`montage_mascot_media_id`, `visual_config_json`); product-truth lineage
(`pi_snapshot_id/version`, `product_truth_digest`, `official_visual_sha256`);
system versions (`compiler_version`, `recipe_schema_version`); and the
set-once prompt-snapshot binding (`status` CHECK ∈(DRAFT,FINALIZED),
`workspace_execution_package_id`, `prompt_fingerprint`, `prompt_snapshot_json`).

**Immutability / exact replay** (`agent/db/creative_execution_recipe_crud.py`).
`get_or_create_recipe` is **idempotent by `recipe_identity_digest`**: the digest
(`_identity_digest`, sorted-key SHA-256) is taken over `{schema, product_id,
production_recipe, candidate_id, copy_text_digest, visual_variation_fingerprint,
visual_resolver_version, requested_total_duration_seconds, generation_mode,
pi_snapshot_id, pi_snapshot_version, treatment_id}`. **Same immutable inputs →
same `recipe_id` = exact replay**; an existing recipe is returned unchanged, never
overwritten. `bind_prompt_snapshot` freezes the compiled reference **exactly once**
(DRAFT→FINALIZED); a FINALIZED recipe returns its stored snapshot unchanged — an
authority change produces a **new** recipe, never a rewrite. Create is
**provider-free** (`create_execution_recipes` resolves copy read-only, resolves
visuals via `auto_visual_variation_service`, and derives the duration/orchestration
plan via `copy_render_service._resolve_execution_duration_plan`).

## 5. Prompt Snapshot / Replay / Remix — REUSE, not a new table

The compiled prompt is snapshotted by **reusing** two existing authorities — there
is **no new snapshot table and no new compiler**:

1. `workspace_execution_package_service.create_workspace_execution_package` — the
   existing **compile-time prompt snapshot** (the WEP: `prompt_fingerprint`,
   `canonical_package_fingerprint`, `compiler_version`, `execution_allowed`,
   blockers). `compile_execution_recipe` calls it provider-free and stores the
   returned reference into the recipe via `bind_prompt_snapshot`.
2. `execution_approval_service` — the **immutable, authority-bound approval
   snapshot/manifest** that later governs any live dispatch (§7, §10).

- **Exact replay.** The same recipe → the same WEP identity/fingerprint. Because
  the WEP is a deterministic compile of the same immutable inputs, replay is
  byte-stable **unless a load-bearing authority changed** (PI snapshot, formula
  version, WPS authority, compiler version) — in which case a **new** snapshot (and
  a new recipe identity) is produced rather than a silent in-place mutation.
- **Remix.** `remix_execution_recipe(recipe_id, *, seed, visual_count)` reuses the
  **same `candidate_id` (same copy identity)** with a **new governed visual
  variation** and **no text-provider call** — it simply re-enters
  `create_execution_recipes` with a new seed, producing new recipe rows + new
  prompt snapshots. Same words, different governed pixels.

## 6. HYBRID / FACELESS / MONTAGE integration — one honest copy authority

Every production recipe consumes the **request-scoped** `BENEFIT_COPY_RENDER_V1`
authority and **never** the product-global Copy Register V2 binding:

- `create_execution_recipes` reads the finalized candidate through
  `copy_render_execution_resolver.resolve_rendered_copy_execution(product_id,
  copy_lane, candidate_id)` (candidate must be LOCKED/FINALIZED; lane must match —
  else `EXECUTION_RECIPE_CANDIDATE_NOT_SELECTED` / `EXECUTION_RECIPE_LANE_MISMATCH`).
- `compile_execution_recipe` passes `copy_v2_context = {"lane": copy_lane,
  "benefit_copy_render": {"candidate_id": …}}` into the WEP compiler, which routes
  through the multiplexer `copy_execution_resolver.resolve_execution_copy`. That
  multiplexer resolves the rendered-copy authority when a `benefit_copy_render`
  selection is present and **otherwise delegates, behaviourally unchanged, to the
  existing product-global / V2 resolver** — "a rendered copy never becomes a V2
  binding."
- **HYBRID** compiles presenter-led (`character_presence="VISIBLE_CREATOR"`,
  `avatar_id`, `scene_template`, `camera_preset` from the resolved descriptor).
  **FACELESS / MONTAGE** compile presenter-free: the recipe re-binds the resolved
  faceless scene identity via `faceless_lane_service.resolve_faceless_scene_authority`
  + `build_faceless_resolution` (`character_presence=FACELESS_CHARACTER_PRESENCE`,
  `avatar_id=None`); **MONTAGE** additionally sets `product_presence_type =
  "PRODUCT_MASCOT"`. A visual that cannot re-resolve fails closed with
  `EXECUTION_RECIPE_VISUAL_UNRESOLVED` — never a degraded default.

## 7. Production Studio / P6 integration (`creative_production_*`)

P6 is the batch orchestrator over the same authorities. Its entire plan lifecycle
is **provider-free** except the final live dispatch:

```
create_plan ─▶ run_capacity_preflight ─▶ materialize_content_matrix ─▶
mark_compilation_ready(compile) ─▶ approve_plan ─▶ assign_waves ─▶
dry_run_plan ─▶ start_plan(live) ── (ONLY here) ──▶ provider payload
```

- **Recipes/status** (`agent/models/creative_production.py`): operator-facing
  `ProductionRecipe ∈ {HYBRID, FACELESS, MONTAGE}` (retired `T2V/F2V/I2V` fail with
  `PRODUCTION_RECIPE_RETIRED`); `PlanStatus` DRAFT→PREFLIGHT_(READY|BLOCKED)→
  PENDING_APPROVAL→APPROVED→SCHEDULED→RUNNING→COMPLETED(_WITH_FAILURES); default
  `variation_strategy` is AUTO treatment/visual selection
  (`SAME_ANGLE_DIFF_DIALOGUE_DIFF_VISUALS`, and `SAME_SCRIPT_DIFF_VISUALS` for the
  same-copy fan-out this factory produces). `CreativeProductionExecutionPolicy`
  pins `credit_policy = "EXPLICIT_CONFIRMATION_REQUIRED"`. Governed model×duration
  is validated through `video_models.resolve_orchestration` (the model/duration
  registry); MONTAGE is `9:16` + SINGLE-clip only.
- **The only provider touch is `start_plan`** (`creative_production_scheduler_service`).
  It is triple-gated: `body.live` must be set (else it degrades to
  `dry_run_plan`); `live_execution_certified()` must hold (runtime licensing —
  else `P6_LIVE_EXECUTION_NOT_CERTIFIED`, 403); and the exact phrase
  `P6_LIVE_CONFIRMATION = "AUTHORIZE_P6_LIVE_CREDIT_SPEND"` must be supplied (else
  `LIVE_CREDIT_CONFIRMATION_REQUIRED`, 403). The plan must be SCHEDULED with a
  complete snapshot and a matching **non-credit dry-run proof**. Dispatch binds a
  **human-approved execution-approval manifest**
  (`execution_approval_service.approved_manifest_id_for_run`); with no approved
  manifest the provider-boundary gate blocks.

## 8. Rendered-output behavioral acceptance (PR #924)

`agent/services/rendered_output_acceptance_service.py` is the shared QC seam that
answers a question an MP4's existence cannot: **did the render actually behave?**
`evaluate_surface_acceptance(surface, media_path, *, product_fidelity_status,
vision_prover, speech_prover, work_dir)` returns a **per-property PASS / FAIL /
UNPROVEN** verdict against the producing surface's exact behavioral property set:

| Surface | Property set (`_SURFACE_PROPERTIES`) |
|---|---|
| **HYBRID** | PRESENTER_VISIBLE · PRESENTER_PRODUCT_INTERACTION · SPOKEN_DIALOGUE_PRESENT · LIPSYNC_PRESENT · PRODUCT_FIDELITY · NON_STATIC_SCENE · BGM_ONLY_FALSE |
| **FACELESS** | HUMAN_PRESENCE · HAND_PRODUCT_INTERACTION · NO_FACE_HEAD · SPOKEN_DIALOGUE_PRESENT · PRODUCT_FIDELITY · NON_STATIC_SCENE · BGM_ONLY_FALSE |
| **MONTAGE** (≡ PRODUCT_MASCOT_MONTAGE) | MASCOT_VISIBLE · MASCOT_IDENTITY_CONTINUITY · MASCOT_ACTIVE_ACTION · SPOKEN_DIALOGUE_PRESENT · LIPSYNC_PRESENT · PRODUCT_FIDELITY · NON_STATIC_SCENE · BGM_ONLY_FALSE |

- **UNPROVEN never silently PASSes.** A property is PASS only when the rendered
  media proves it. Cheap falsifications run locally (`analyze_motion` → a truly
  frozen clip is a proven `NON_STATIC_SCENE` FAIL that overrides any prover;
  `analyze_audio`/`probe_media` → no audio stream is a proven
  `SPOKEN_DIALOGUE_PRESENT` FAIL). Vision properties (presence/hands/face/mascot/
  lip-sync) and trustworthy dialogue-vs-BGM stay **UNPROVEN** unless a
  `vision_prover` / `speech_prover` is injected (Round 4). Overall status is
  `BEHAVIORAL_ACCEPTANCE_FAIL` if any FAIL, else `BEHAVIORAL_REVIEW_REQUIRED` if any
  UNPROVEN, else `BEHAVIORAL_ACCEPTANCE_PASS`; `acceptance_gate_status` treats FAIL
  **and** REVIEW as non-success. Provider-free, degrades safely (no ffmpeg ⇒
  UNPROVEN, never a false PASS). Wired at retrieval in
  `agent/services/make_video.py` (records `behavioral_acceptance_status` /
  `_surface` on the job).

## 9. Legacy / UI cutover

- **Benefit On-Demand Copy is the normal copy authority.** In the dashboard the
  On-Demand Copy Renderer (R2) → execution-recipe (R3) path is the default authoring
  route (`CreativeProductionStudioPage.tsx`). **Existing Approved Copy V2** remains
  available as **compatibility/maintenance** only, mutually exclusive per Prepare,
  and is never overloaded by the rendered-copy path (`copyReady` vs `v2CopyReady`).
- **Legacy normal authoring is deactivated** (data retained). FAST54 /
  Storyboard-Landbank-V3 normal authoring is out of the normal workflow; the legacy
  copy runtime is retired by construction —
  `agent/models/copy_blueprint_v2.legacy_copy_maintenance_enabled()` is a
  permanently-`False` stub (Task D4: no operator switch re-enables legacy
  copy_set / copy_component / poster_copy_set reads/writes; recovery is an offline
  migration, not a runtime toggle).
- **Avatar metadata is sufficient** for copy/recipe authoring. The visual resolver
  reads governed avatar **metadata** (`avatar_registry.resolve_presenter` wardrobe,
  scene-derived camera) — a **generated avatar image is not required** to author
  copy or build a recipe; pixels are the video engine's job at execution time.

## 10. Provider / credit boundaries

- **IMAGE generation is credit-free; only VIDEO spends credits.** Nothing in the
  R1→R3 authoring path (copy render, visual resolve, recipe create, compile, prompt
  snapshot, P6 plan through dry-run) spends credits.
- **SweetWPS is a CEILING, not an exact target** (`video_continuity_contract.py`):
  `ERR_DIALOGUE_SWEETWPS_UNDERRUN` is legacy and **no longer raised** (a script may
  occupy *less* than the SweetWPS budget); only
  `ERR_DIALOGUE_SWEETWPS_OVERRUN` still fails closed. Duration→word budget is the
  single canonical authority (`resolve_dialogue_occupancy_targets` /
  `build_temporal_occupancy_receipt`), never re-implemented per surface.
- **The credit chokepoint is `flow_client` + the execution-approval manifest.**
  Every credit-bearing video method crosses one provider boundary tagged
  `captchaAction == "VIDEO_GENERATION"`; `execution_approval_service.video_dispatch_unauthorized_reason`
  blocks any dispatch that lacks an authorised, human-approved manifest (the Final
  Prompt Approval Gate, inert unless `EXECUTION_APPROVAL_GATE_ENFORCED`). Paid video
  is additionally gated by P6 runtime licensing (`live_execution_certified()`) and
  the operator confirmation phrase (§7).

## 11. Closure / proof matrix

Every hop from rendered copy to the provider boundary is provider-free and
fail-closed; the single credit act sits behind explicit, human-approved gates.

| Stage | Authority (reused / new) | Provider calls | Fail-closed gate |
|---|---|---|---|
| Rendered copy (R2) | `copy_render_service` → `BENEFIT_COPY_RENDER_V1` | 0 (cache) / 1 stitch | claim-safe · formula-exact · WPS ceiling · text-unique |
| Copy → recipe read | `copy_render_execution_resolver.resolve_rendered_copy_execution` | 0 | LOCKED/FINALIZED + lane match |
| Visual resolve | `auto_visual_variation_service.resolve_visual_variations` | 0 | governed pool empty ⇒ typed error; reuse recorded |
| Recipe create | `creative_execution_recipe_service.create_execution_recipes` | 0 | idempotent by `recipe_identity_digest` (exact replay) |
| Compile | `compile_execution_recipe` → `create_workspace_execution_package` | 0 | unresolved visual ⇒ `EXECUTION_RECIPE_VISUAL_UNRESOLVED` |
| Prompt snapshot | `bind_prompt_snapshot` (WEP + approval snapshot reuse) | 0 | set-once DRAFT→FINALIZED; immutable |
| Package / multiplexer | `copy_execution_resolver.resolve_execution_copy` | 0 | rendered copy never a V2 binding |
| P6 plan | `creative_production_*` create→preflight→matrix→compile→approve→waves→dry-run | 0 | AUTO selection; capacity/claim preflight |
| Live dispatch | `start_plan` → `flow_client` | **video only** | `live_execution_certified()` + `AUTHORIZE_P6_LIVE_CREDIT_SPEND` + approved manifest |
| Output QC | `rendered_output_acceptance_service.evaluate_surface_acceptance` (PR #924) | 0 | UNPROVEN/FAIL never silent-pass |

## Files (Round 3)

**New.** `agent/services/auto_visual_variation_service.py`,
`agent/models/creative_execution_recipe_v1.py`,
`agent/db/creative_execution_recipe_crud.py`,
`agent/services/creative_execution_recipe_service.py`,
`agent/api/creative_execution_recipe.py`,
`agent/services/rendered_output_acceptance_service.py`, plus the Production Studio
pack (`agent/models/creative_production.py`,
`agent/services/creative_production_plan_service.py`,
`creative_production_scheduler_service.py`, `creative_production_compile_service.py`,
`creative_production_recipe_service.py`, `agent/api/creative_production.py`,
`dashboard/src/pages/CreativeProductionStudioPage.tsx`,
`dashboard/src/api/creativeProduction.ts`), and tests.
**Edited (additive).** `agent/db/schema.py` (`CREATIVE_EXECUTION_RECIPE_SCHEMA`
const + `executescript`), `agent/main.py` (router wire),
`agent/services/make_video.py` (behavioral-acceptance hook). Never mutates
`copy_render_*` or the Copy Register V2 binding.

## Boundary

- **Round 4 (not built):** injected `vision_prover` / `speech_prover` so the PR
  #924 UNPROVEN properties can resolve to a real PASS/FAIL instead of routing to
  behavioral review; live P6 credit-spend certification at scale.
- **Frozen / untouched:** Copy Register V2 persisted resolver (delegated to
  unchanged), the canonical prompt compiler, the video engines, and the deprecated
  FAST54 / Storyboard-Landbank-V3 authoring (data retained, out of the normal flow).
