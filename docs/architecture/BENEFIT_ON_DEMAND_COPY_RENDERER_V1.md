# Benefit On-Demand Copy Renderer — V1 (Round 2)

**Status:** implemented · provider-free tests green · one live STRUCTURE call gated
behind CI-green + merge + safe deploy.
**Baseline:** `origin/main = 9b843278`. Builds on Round 1 (Benefit-Centric Creative
Factory, merged `749573e`).

## Law
**SYSTEM OWNS STRUCTURE** (selection / formula / duration / WPS / cache /
idempotency) · **AI ONLY STITCHES** (arranges Round-1 atom seeds into complete
spoken scripts) · **VIDEO ENGINE OWNS VISUAL EXECUTION** (unchanged).

Copywriting for the **HYBRID** and **FACELESS** lanes becomes: Product → Benefit →
Target count → Duration → *Generate 5 Suggestions* → lock / regenerate until the
target is met → finalize → N independent **READY** prompt packages.

## Pipeline
```
VERIFIED, atom-ready Benefit + duration + target (1 ≤ target ≤ unique capacity)
  │ deterministic recipe selector (0 provider calls): ACTIVE atoms + within-Angle
  │   compatibility, diversity-preferring, excludes session-USED fingerprints → ≤5
  ▼ ONE bounded STRUCTURE stitch call (lane="structure", allow_fallback=False),
  │   idempotent (request_id) + single-flight + crash-recoverable
  │ provider → ordered stage text per slot → system derives
  │   full_copy_text / word_count / text_digest / stage_json
  │ BATCH-ATOMIC validation: claim-safe · formula-stage-exact · word ≤ budget ·
  │   fingerprint-unique · full-copy text-unique within batch AND vs session history
  ▼ lock / unlock / regenerate / finalize (0 provider calls)
  ▼ immutable render-artifact CACHE (render_key hit ⇒ 0 provider calls)
  ▼ execution-copy MULTIPLEXER → BENEFIT_COPY_RENDER_V1 (honest, request-scoped)
  ▼ existing compiler → N create_workspace_execution_package = N READY packages
      (NO production_queue enqueue · NO video · NO Flow · NO Copy-V2 binding write)
```

## Distinct, honest authority (no V2 spoof)
A finalized rendered candidate resolves — through a thin multiplexer at the
package-materialization boundary — into the **same compiler-copy shape** the
canonical prompt compiler already consumes (`compiler_copy_intelligence` +
`approved_dialogue`), but as a **distinct authority**:

- `authority_kind = "BENEFIT_COPY_RENDER_V1"`, `v2_enabled = False`,
  `binding = None`, `projection = None`.
- Consumers gate on a neutral `copy_ready` property: for `COPY_BLUEPRINT_V2` it is
  exactly `v2_enabled` (the V2 path is behaviour-identical); for the renderer it is
  `status == "READY"`. A rendered copy is **never** presented as a V2 binding, and
  the product-global Copy Register V2 pointer is never written.
- When no `benefit_copy_render` selection is present, the multiplexer delegates to
  the existing persisted-V2 resolver unchanged (proven byte-for-byte in tests).

## System-owned structure
- **Selection** (`copy_render_combination_service`, 0 calls): enumerate valid
  recipes `(benefit, angle, hook, body, cta)` — compatibility triples when present,
  else the within-Angle Cartesian — drop session-USED fingerprints, pick ≤5 by a
  reproducible `sha256(session_id:batch)`-seeded diversity strategy (new Angle →
  Hook → Body → CTA). Unique capacity = count of valid recipes (compat-narrowed).
- **Formula** (strict): `copy_blueprint_v2_authority` (default `PAS`
  = problem→agitate→solution→cta). Unknown formula **fails closed**.
- **Duration → word budget** (canonical): `canonical_duration_word_budget`
  (`total_dialogue_word_budget`, GOOGLE_FLOW, SWEET). Never re-implemented.
- **Provider**: `ai_copy_provider_adapter.complete_json_with_receipt(...,
  lane="structure", allow_fallback=False)` — the same seam Round 1 uses; one call
  per Generate/Regenerate; the global structure-fallback setting is never mutated.

## Idempotency, single-flight, crash recovery
`POST /sessions/{id}/suggestions` requires a client `request_id`. A
`UNIQUE(session_id, request_id)` insert reserves a batch through the
`RESERVED → RUNNING → SHOWN/FAILED` lifecycle; the selected recipe/slot plan is
persisted **before** any provider work. A duplicate `request_id` replays the
existing batch with **no** second call; a concurrent authoring request is refused
(`COPY_RENDER_BATCH_IN_PROGRESS`); a stale RESERVED/RUNNING batch is reconciled to
`FAILED` (`UNKNOWN_OUTCOME` for RUNNING) — never auto-repeated. A retry is a **new**
`request_id`.

## Cache + staleness (full lineage)
`render_key = sha256(product_truth_lineage · benefit_digest · recipe_fingerprint ·
formula_id · formula_version · duration · target_language · wps_mode ·
wps_authority_version · wps_authority_digest · renderer_prompt_version ·
safety_policy_version)`. A batch resolves cache hits first; at most ONE provider
call covers all misses; all hits ⇒ `provider_calls = 0`. Session staleness binds
the same lineage plus `atom_build_fingerprint` — a deterministic digest of the
ACTIVE atom set **and** the active compatibility map, so a compatibility-map change
stales the session even when the benefit text is unchanged. Visual settings
(avatar / wardrobe / background / scene / camera / treatment) are **excluded** —
they never stale copy.

## Session laws
- **Target:** `1 ≤ target ≤ unique_capacity`, editable up (≤ capacity) before
  finalize, never below `locked_count`. `target > capacity` ⇒
  `COPY_RENDER_TARGET_EXCEEDS_CAPACITY` (provider-free).
- **Lock:** SHOWN→LOCKED; `locked > target` refused; `locked == target` ⇒
  `TARGET_COMPLETE` and Regenerate is disabled **server-side**.
- **Unlock:** LOCKED→SHOWN (stays visible + re-lockable); the fingerprint remains
  USED; reopens the target.
- **Regenerate (failure-atomic):** in one transaction — unlocked SHOWN→SKIPPED,
  new→SHOWN, LOCKED untouched. Any validation failure ⇒ batch FAILED, current
  SHOWN + LOCKED untouched, no auto-retry / no second model.
- **Finalize (atomic):** requires `locked == target`; one transaction sets the
  session and every LOCKED candidate → FINALIZED (+`finalized_at`).
- **Text uniqueness is session-history-wide:** a full-copy `text_digest` never
  repeats across SHOWN/LOCKED/SKIPPED/FINALIZED; cache-hit selection skips an
  artifact that would duplicate prior/in-batch text.

## prepare-selected — N READY packages (no production)
`POST /sessions/{id}/prepare-selected` (FINALIZED only) reads **only FINALIZED**
candidates and calls `create_workspace_execution_package` once per candidate with
`copy_v2_context = {lane, benefit_copy_render: {candidate_id}}`. Each binding is
persisted `UNIQUE(session_id, candidate_id)`, so the operation is idempotent and
candidate-exact and a part-way failure re-converges. It returns the N packages with
honest per-package readiness/blockers. It performs **zero** `production_queue`
enqueue, run, video, Flow, or production_status change.

## Auth + lane scope
Every endpoint requires an authenticated human session (401). Mutations also require
`products.update` (403). Benefit copy is strictly HYBRID/FACELESS
(`COPY_RENDER_LANE_UNSUPPORTED` otherwise). In the UI, Benefit On-Demand Copy
(default) and Existing Approved Copy V2 (advanced) are mutually exclusive per
Prepare; the neutral `copyReady` state routes to a finalized rendered selection or
to `v2CopyReady` per source — `v2CopyReady` is never overloaded.

## Data model (`COPY_RENDER_SCHEMA`, additive)
`copy_render_session` · `copy_render_batch` (`UNIQUE(session_id, request_id)`) ·
`copy_render_artifact` (`render_key UNIQUE` — immutable cache) ·
`copy_render_candidate` · `copy_render_candidate_package`
(`UNIQUE(session_id, candidate_id)`). Never mutates any pre-existing table.

## Provider policy
Zero live TEXT/VIDEO calls during implementation and tests (injected fakes; the real
adapter's process-global counter is asserted flat). Exactly ONE final live STRUCTURE
text call after CI-green + merge + safe deploy (`deepseek-v4-flash`,
`allow_fallback=False`, no Pro/Luna, no retry). No live video.

## Files
**New:** `agent/models/copy_render_v1.py`, `agent/db/copy_render_crud.py`,
`agent/services/copy_render_combination_service.py`,
`agent/services/copy_render_service.py`,
`agent/services/copy_render_execution_resolver.py`, `agent/api/copy_render.py`,
`dashboard/src/api/copyRender.ts`,
`dashboard/src/components/copywriting/OnDemandCopyRendererPanel.tsx`,
`dashboard/src/components/copywriting/BenefitCopySourceSection.tsx`, tests.
**Edited (additive):** `agent/db/schema.py` (schema const + executescript),
`agent/main.py` (router wire), `agent/services/copy_execution_resolver.py`
(`authority_kind` + `copy_ready` + `resolve_execution_copy` multiplexer — existing
V2 path unchanged), `agent/services/workspace_execution_package_service.py` (route
resolve through the multiplexer, gate on `copy_ready`),
`dashboard/src/pages/OperatorPage.tsx`, `dashboard/src/pages/FacelessVideoPage.tsx`
(copy-source toggle + neutral `copyReady`).
