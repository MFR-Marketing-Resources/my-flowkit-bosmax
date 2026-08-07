# HANDOVER — V4 Workflow Shell rollout + Creative-config → generation wiring

**Date:** 2026-08-07
**From:** Claude Code (review/architecture + scoped implementation)
**To:** Codex (implementation)
**Branch:** `wip/v4-workflow-shell` (LOCAL ONLY — not pushed). Base: `main` recent commits already carry the recipe model (Step C–F) + `5b815ba`.
**Read first (repo contract):** `AGENTS.md`, `.ai/status/CURRENT_STATE.md`, `.ai/contracts/*`, `.ai/ENGINEERING_LOCKDOWN.md`. This handover is *subordinate* to those.

---

## 0. TL;DR — what Codex must do next

Two parallel workstreams, both AGREED with the owner:

1. **Roll the T2V V4 guided-shell UI/UX to every other lane** — F2V, Hybrid, I2V, IMG, IMG Fastlane, IMG Cockpit, Poster Builder, Production Studio (P6). T2V is the DONE reference; reuse the shared kit, don't reinvent.
2. **Finish "Creative config → generation" (Phase B)** — make the approved Creative Setup config (avatar × scene, camera-follows-scene) actually DRIVE mass/bulk video with diverse coherent treatments. B0/A.2 is done; B1/B2/B3 remain.

**Hard rules:** surgical/additive only · governed compiler + one-door generation are LOCKED (additive, never rewrite) · NEVER spend credits/DeepSeek without explicit owner approval · NEVER revive the dead DOM lane (ADR-007) · run `scripts/verify-gate.ps1` before reporting green · commit to a wip branch at every checkpoint (this repo has a history of co-tenant `git` wipes) · do NOT push/PR without owner authorization.

---

## 1. What is already DONE (4 commits on `wip/v4-workflow-shell`)

| SHA | What |
|---|---|
| `ad20fb9` | **V4 guided single-page T2V shell** — new kit `dashboard/src/components/workflow/` (WorkflowStep, ResolvedChip, StoryboardStrip, QueueRow, OperatorCockpit + barrel + `workflow-kit.test.tsx`); teal/violet tokens `--color-v4-accent / -accent-ink / -auto` added additively to `dashboard/src/index.css` `@theme`. `OperatorPage.tsx` gained a V4 render branch (7 guided steps + cockpit rail), **default** for `/operator/t2v`; classic reachable at `?classic=1`. Reuses ALL existing state/handlers → the Step-F payload (`recipes[0] → scene_template_id/camera_preset_code`, `avatarCodes[0] → avatar_id`) is preserved by construction. Two classic-UI component tests pinned to `?classic=1`. |
| `2530a42` | **Creative Setup UI = recipe-coherent** — `CreativeSetupPanel.tsx`: removed the independent "Camera presets" pick list (the only source of incoherent combos); config is now avatar × scene; camera shown **read-only per scene** ("SCN-xxxx · Variation N · 🎥 BODY_A") and derived on save. |
| `5eb6f17` | **B0/A.2 server enforcement** — `creative_setup_service.save_creative_selection` now DERIVES `selected_camera_preset_codes` from the chosen scenes via the bridge and IGNORES any caller-supplied camera (enforced for EVERY caller, not just the UI). New SSOT helper `creative_recipe_service.camera_for_variant(variant) -> str`. Tests updated to the new contract (setup + handoff). |
| `022e3ac` | **Single-clip T2V generation enabled** — V4 Step 7 now offers a "▶ Generate 1 clip · Ns" button for SINGLE mode, wired to `handleExecute → POST /api/flow/generate → make_video.start_generate` (the LIVE proven one-door lane, ADR-007 compliant). Operator-pressed only (spends credits, never auto-fired). EXTEND still uses `NativeExtendPanel`. |

**Local proof at handover:** `npm run build` OK (tsc -b + vite); `npx vitest run` = **581/581** (stable across re-runs); relevant backend pytest green (`test_creative_setup_service`, `test_creative_recipe_service`, `test_creative_setup_api`, `test_creative_handoff_service`, etc.). Full `scripts/verify-gate.ps1` was NOT run end-to-end for these — **Codex should run it before any push.**

**Runtime state:** local agent restarted (`scripts/start-local-agent.ps1 -ForceRestart`, PID 30084) so the B0/A.2 `.py` edits are live; dist rebuilt (bundle hash changes each build). Live-verified: V4 default page, coherent Creative Setup, single-clip button renders. The single-clip generate was driven live to the **fallback-confirm gate** (compile ✓, prepare ✓) but NOT fired — the actual generate is the owner's press (credits) and needs an open+warm Google Flow editor tab.

---

## 2. Owner decisions (LOCKED — do not relitigate)

- **One design system for ALL lanes.** T2V V4 is the reference. Each lane = the SAME shell + kit, differing only by capability config (see §4).
- **Accent identity = teal + violet** (`--color-v4-*`), applied to V4 surfaces, spreading as lanes roll over. App elsewhere stays slate/blue until migrated. Dark-theme only (the app has no light mode).
- **V4 is the default, classic is a transitional `?classic=1` fallback to be DELETED once V4 is proven in daily use.** Do not keep two permanent pages ("jangan banyak page dan sampah").
- **Simplicity is the product.** The knowledge base resolves as much as possible; the operator makes the fewest choices. Progressive disclosure (active step open, done steps collapse to a one-line summary).
- **Camera FOLLOWS the scene — never an independent axis** (bridge-derived). True in UI and server.
- **Creative direction = single-select** (pick ONE scene; camera follows). Multi-select/fan-out is a separate bulk concern (§5).
- **Single-clip AND Extend must both be selectable + generatable.** Done for T2V.
- **Cockpit doubles as the video-review screen** when a job completes.
- **No verbose metadata on operator screens** (owner explicitly rejected the "Coherent recipes — each row is…" blurb, cluster labels, etc.).

---

## 3. Architecture facts Codex needs (with citations)

### 3.1 The recipe model (deterministic, FREE — no AI, no credits)
- A **recipe** = a coherent `(avatar, scene, camera)` tuple where **camera is derived from the scene** via the 7-row bridge `agent/authority/creative_scene_variation_camera_bridge.json` (`variation_of` → `(block_purpose, content_type)` → `camera_for_variation` → `block_content_mapping.recommended_preset`). Var1→BODY_A, Var5→BODY_B, Var7→CTA_B, Var4→BODY_D.
- Avatars are gender+cluster filtered; scenes are cluster filtered. `agent/services/creative_recipe_service.py` (`build_recipes`, `pretick_recipes`, `generate_product_recipes`, `recipes_from_setup`, **new** `camera_for_variant`).
- FE: `getProductRecipes(productId)` (`dashboard/src/api/creativeIntelligence.ts`) → `{recipes, recommended_pretick, cluster, review_required}`. Used by the V4 operator (single-select) and `CreativeSetupPanel` smart-suggest.

### 3.2 Creative Setup config (the SSOT-in-progress)
- Table `creative_product_selection` (`agent/db/schema.py`): `selected_avatar_code(s_json)`, `selected_scene_template_id(s_json)`, `selected_camera_preset_code(s_json)`. DRAFT → APPROVED review gate. Camera lists are now DERIVED (B0/A.2).
- Service `agent/services/creative_setup_service.py` (`resolve_creative_setup`, `save_creative_selection`, `review_creative_selection`, `bulk_auto_setup`).
- **Known linkage gap (this is Phase B):** P6 reads only the AVATAR list from the saved selection (`creative_production_plan_service._selection_avatar_codes ~L1748`); **scene/camera never reach generation** (comment at `creative_setup_service.py ~L341-346`). Treatment authoring uses the **singular primary** scene/camera (`creative_treatment_service._resolve_selection_handoff ~L650-652`), so authoring N treatments repeats the same scene.

### 3.3 Generation lanes (READ CURRENT_STATE.md §one-door)
- **One-door (LIVE, PROVEN, ADR-007-compliant):** `POST /api/flow/generate` → `make_video.start_generate` (`agent/api/flow.py:860`, `agent/services/make_video.py:280`). Produces + saves ONE clip; T2V needs no reference; **rejects multi-block prompts** (`flow.py:870`, `MULTI_BLOCK_PROMPT_REJECTED`). Dashboard also reaches the same door via `POST /api/flow/execute-flow-job → _run_manual_job_via_generate` (`flow.py:3044-3053`). **Spends credits** on success (`make_video.py:928`). Binds to the OPEN Flow editor (fail-closed if none).
- **EXTEND (durable, canonical for >8s):** `NativeExtendPanel` → `POST /api/flow/video-jobs/plan|authorize|start` (`flow.py:1609/1655/1953`) → `video_production_orchestrator.advance_job` (INITIAL 8s via the one-door + N native-extend continuations + CONCAT). Duration must be a multiple of 8 and ≥16 (`video_production_orchestrator.py:219-224`). ADR-009.
- **FORBIDDEN — the dead DOM lane:** `extension/content-flow-dom.js` DOM-driving lanes, `extension/f2v-flow-queue-runner.js`, GFV2 DOM lane in `extension/background.js`. Delete-only. NEVER repair/extend/expose. (ADR-007 §FROZEN.)
- **The single-clip UI block was UI-only** (`OperatorPage.renderModule()` ~L1988-2012) — a prior UX choice (ADR-009 "one canonical control"), NOT an architectural prohibition. Re-enabling single-clip via the one-door (done, `022e3ac`) is additive + compliant.
- **Copy is NOT a hard gate.** `create_workspace_execution_package` fails closed only when neither `copy_set_id` nor `copy_fallback_confirmed` is set; fallback-confirm proceeds (stamped `NOT_SELECTED/landbank_fallback`). The fallback-confirm modal is a `data-rpa-stop` human gate — do NOT auto-click it in automation.
- **Open T2V caveat (telemetry only):** T2V post-approve model verification reports `model_unverified` (flagged, not failed) because the text-only tool name isn't yet in `_GEN_TOOLS` (`make_video.py:787-789`, CURRENT_STATE.md:134-136). Generation itself works.

### 3.4 The V4 kit + shell pattern (the reference to replicate)
- Kit: `dashboard/src/components/workflow/` — `WorkflowStep` (numbered, states done/active/upcoming, progressive-disclosure summary), `ResolvedChip` (knowledge-resolved value + AUTO marker + optional Tweak), `StoryboardStrip`, `QueueRow`, `OperatorCockpit` (right rail: product mini → plan rows → queue/children → Generate CTA + credit note → collapsed Debug drawer).
- Shell: `OperatorPage.tsx`, `const useV4 = new URLSearchParams(location.search).get("classic") !== "1"`, `if (useV4 && mode === "T2V") { return <V4 layout> }` before the classic return. Root keeps `data-testid="hybrid-workflow"` + `data-variant="v4"` + `data-mode` (RPA-selector contract).
- T2V step order: Product → Message & angle → Presenter (single avatar) → Length (+ Advanced drawer: engine/model/language/camera-style/presence) → Creative direction (single-select scene→camera list) → Storyboard (from `compileWorkspacePromptPreview`) → Generate video (SINGLE = one-door button / EXTEND = NativeExtendPanel). Cockpit rail = plan + compile/prepare CTA + review-video-on-complete + Debug.

---

## 4. TASK A — roll the V4 shell to the other lanes

**From the read-only map (agents), the lanes fall into 3 buckets:**

**Bucket 1 — already share `OperatorPage` (cheapest): F2V, Hybrid, I2V, IMG.**
- All render through `OperatorPage.tsx` driven by the `mode` prop. The V4 branch is currently gated `mode === "T2V"` only.
- Do: generalize the V4 branch to these modes. Per-mode differences are small and already branch by `mode` in the classic path:
  - **Reference binding** — `CanonicalReferenceBindingControls` (F2V start/end frame; I2V character+scene+style; HYBRID product ref). `referenceBindingBlocker(mode, binding)` is the gate (T2V returns null). Add a "Reference" step to the V4 flow for these modes.
  - **HYBRID** registry-authority avatar/scene pickers (classic ~L2446-2536) — reconcile with the V4 presenter step.
  - **IMG** renders a live `IMGModule` (the only mode whose `renderModule()` returns a module) — fold IMG's asset/prompt/settings into a V4 IMG step, or keep `IMGModule` inside a V4 step body. IMG generate already uses `handleExecute` (insert-then-stop lane) — keep its existing behavior.
- Reuse the SAME cockpit; feed it per-lane plan rows. Keep the Step-F payload wiring intact per mode (see `runGeneratePackage` payload, each mode's reference fields).

**Bucket 2 — standalone pages that reuse leaf components: IMG Fastlane (`ImgFastlanePage.tsx`), IMG Cockpit (`ImgCockpitPage.tsx`).**
- They already reuse `SearchableProductSelect`, `VisualAssetPicker`, `ApproveAssetModal`, copywriting components. Re-skin with the kit (WorkflowStep/OperatorCockpit) and the image-gen settings as a "Length↔Count" swap (images have count, not duration). Cockpit "queue" = the results gallery; "review" = the approved asset.

**Bucket 3 — bespoke, do NOT force into the single-shot shell: Poster Builder (`PosterBuilderPage.tsx`, tri-modal Auto/Guided/Controlled), Production Studio P6 (`CreativeProductionStudioPage.tsx`, batch/matrix orchestration).**
- Apply the design LANGUAGE (kit components, teal/violet tokens, cockpit-style summary rail) but keep their intrinsic IA (tri-modal / batch). Link out from the shared shell rather than hosting them inside it.

**Rollout mechanics:** same as T2V — build the V4 render additively behind the `?classic=1` toggle so the working page never breaks; flip default per lane once verified; delete the classic branch after the owner is happy. Update any classic-UI component tests to `?classic=1` (pattern already set in `022e3ac`/prior commits).

---

## 5. TASK B — Creative config → generation (Phase B). B0/A.2 DONE; B1/B2/B3 REMAIN.

Owner concern was "config too open → bulk guesses → wasted tokens." **Investigation verdict: combo resolution is already deterministic + FREE (no AI); nothing guesses.** So B1–B3 are about *diversity + actually wiring the config through*, not fixing guessing. Maps to backlog tasks **#53, #54, #55**.

- **B0 / A.2 — DONE (`5eb6f17`).** Server derives camera from scene; config can never carry an incoherent camera.
- **B1 (#53) — scene rotation (CODE, zero token).** Add `_selection_scene_template_ids` (mirror `_selection_avatar_codes`, `creative_production_plan_service.py ~L1748`) and thread a per-treatment scene into `creative_treatment_service._resolve_selection_handoff` (~L650) so authoring N treatments spans the config's avatar × scene tuples, camera derived per scene via `creative_recipe_service.camera_for_variant`. `creative_recipe_service.build_recipes` already produces the full coherent grid — it just isn't consumed by production yet.
- **B2 (#54) — handoff for the dedupe ledger.** The ledger EXISTS and is DONE (`creative_production_item.dedupe_guard_key` UNIQUE on `creative_dna_sha256`, which already spans avatar/scene/camera — `schema.py:3466-3467`, `creative_production_plan_service._creative_dna_payload ~L2162`). The gap is getting the config scene/camera into the DNA dimensions so it dedupes on the ACTUAL tuple. **Design decision to make with the owner:** the DNA's camera is `camera_composition` (scene-strategy `camera_route`), a DIFFERENT vocabulary from the bridge camera (`BODY_A` etc.) — reconcile which is authoritative before wiring.
- **B3 (#55) — diverse-plan backfill.** After B1, a deterministic (zero-token) backfill authoring one treatment per recipe tuple per product. **Back up `flow_agent.db` first** (pattern: `flow_agent.db.prerecipe-<ts>`).

**Generation-purity invariant (DO NOT BREAK):** these 5 files must NOT reference the strings `creative_setup_service`, `creative_product_selection`, `creative_avatar_recommendation_service`, `creative_product_selection`: `canonical_prompt_compiler.py`, `ai_copy_assist_service.py`, `copy_grounding_service.py`, `copy_binding_service.py`, `workspace_execution_package_service.py`. (`creative_recipe_service` / scene / camera services are allowed.) There is a guard test: `test_creative_setup_service.py::test_invariant_generation_services_do_not_reference_creative_setup`.

---

## 6. Guardrails / lockdown (mandatory)

- **Surgical + additive.** Don't fix what isn't broken. No formatter noise, no unrelated files, no broad rewrites. Stop and ask if scope expands.
- **LOCKED paths — additive only, never rewrite:** the governed canonical prompt compiler, the one-door generation lane (`make_video.start_generate`), the EXTEND orchestrator, the negotiation brain, retrieval/artifact library.
- **NEVER spend credits / run DeepSeek / fire generation** without explicit, per-action owner approval. Compile/prepare are free; the actual generate is the owner's press. The `data-rpa-stop` fallback gate is a human stop.
- **NEVER revive the DOM lane** (ADR-007). Delete-only for frozen DOM files.
- **verify-gate before green:** `scripts/verify-gate.ps1` (real `npm run build` = tsc -b + vite build, vitest, backend pytest smoke, mandor-check). `tsc --noEmit` alone is NOT sufficient. Report its result as local proof only.
- **Restart to clear stale backend:** editing `agent/**.py` while the agent runs makes it stale ("Backend needs restart" banner locks production). Run `scripts/start-local-agent.ps1 -ForceRestart` from repo root; verify `/api/local-agent/version-proof`. FE-only edits don't need a restart (backend serves dist statically; browser hard-refresh picks up the new hashed bundle).
- **Commit hygiene:** commit each verified increment to the wip branch (this repo has lost staged work to a co-tenant `git` before). Do NOT push/PR without owner authorization. Stage ONLY your files (the tree has many unrelated untracked db-backups/outputs).
- **Live-verify honestly.** Don't claim runtime-green without runtime evidence. The in-app browser + a small DOM/JS inspection is the pattern used here.

---

## 7. Live-verify pattern that worked

1. Rebuild dist (`cd dashboard && npm run build`).
2. Restart agent only if `agent/**.py` changed.
3. Browser → `http://127.0.0.1:8100/operator/<lane>` → hard-refresh; confirm bundle hash matches the new build via the `BackendVersionBanner` line ("backend <sha> … bundle index-XXXX.js").
4. Drive the FREE steps (product select → Compile preview → Prepare final prompt) and inspect DOM state; STOP at the credit-bearing Generate (owner presses).

---

## 8. Backlog / task IDs (owner's numbering)

- **#53** Supply-factory scene rotation (= B1). PENDING.
- **#54** Handoff + ledger per-item avatar×scene×camera dedupe (= B2; ledger done, handoff pending). PENDING.
- **#55** Populate diverse plan for ALL products (= B3, backfill). PENDING.
- **#57** Manual lanes pre-fill pickers from creative setup (knowledge-driven) — related to Task A rollout.
- **Task A** (V4 rollout to 8 lanes) — new, agreed, not yet ticketed.
- **Follow-ups noted earlier:** `refresh_auto` notes-heuristic (PR#651 review #1), gender-regex edge cases, `supersede_open_review_drafts` atomicity; Prompt Handoff Bank not inheriting recipe ids. Low priority.

---

## 9. First moves for Codex (suggested order)

1. `git log --oneline -6 wip/v4-workflow-shell` + read the 4 commits' diffs to absorb the V4 pattern.
2. Run `scripts/verify-gate.ps1` to confirm a clean baseline on the branch.
3. **Task A, Bucket 1 first:** generalize the V4 branch in `OperatorPage.tsx` to F2V/Hybrid/I2V/IMG (add the Reference step, reconcile HYBRID registry pickers, fold IMGModule). Verify each mode at `?classic=1` (old) and default (new). This is the highest-leverage, lowest-risk next step and directly extends the reference.
4. Then Task B / B1 (scene rotation) as a separate, test-first backend increment.
5. Checkpoint-commit each; keep the owner in the loop before flipping defaults or deleting the classic branch, and before ANYTHING that could spend credits.
