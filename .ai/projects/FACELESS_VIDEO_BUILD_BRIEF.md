# BUILD BRIEF — Faceless Video (BOSMAX operator lane)

**Status:** NOT STARTED · greenfield · **additive**. ✅ READY TO BUILD — it rides the
already-hardened, live-proven I2V/F2V one-door; **no engine work is required**.
**Owner:** Faris (farisdatosheikh). **Authored by:** Claude Code (review/architecture).
**Build agent:** any implementation-capable AI (Codex is primary per ADR-002).
**Branch:** create a wip branch from the current V4 tip (`wip/v4-workflow-shell`) —
see §8. Never push/PR without owner authorization.
**Read first (do NOT skip — this brief is SUBORDINATE to them):** `AGENTS.md` ·
`.ai/status/CURRENT_STATE.md` · `.ai/ENGINEERING_LOCKDOWN.md` ·
`.ai/handovers/HANDOVER-2026-08-07-v4-rollout-and-creative-config.md` (the V4 shell pattern).

---

## 0. TRIGGER

Paste this to start the build:

```
BUILD: FACELESS VIDEO MODULE
Read .ai/projects/FACELESS_VIDEO_BUILD_BRIEF.md in full, then AGENTS.md +
.ai/status/CURRENT_STATE.md + .ai/ENGINEERING_LOCKDOWN.md. Build additively as a NEW
V4 operator lane (separate UI, shared engine). Start at Round 1. Do NOT touch the
sealed native-extend lane or the one-door engine internals. Do NOT spend credits /
fire generation without my explicit press.
```

---

## 1. TL;DR — what to build

A **"Faceless Video"** lane in the V4 workflow shell:

> pick a product → resolve or generate a **scene/product image** (no presenter face) →
> **animate that image into ONE short clip** (image-first, duration from user settings) →
> *(optional)* voiceover + text overlay + music → **batch** across N products.

It is BOSMAX's equivalent of SESAAT's **GOYANG** module (verified: GOYANG = Phase 1 image
→ Phase 2 single video, "standard, no extend", batch). Built entirely on the **API-first
one-door** — never the dead DOM lane.

"Faceless" = the base image is a **product/scene** (true faceless). The same lane also
supports an **avatar-holding-product** variant later (BOSMAX has an avatar registry), but
default and priority is the product-only faceless case.

---

## 2. The golden rule (why this is safe)

**Separate UI lane, SHARED engine.** New lane UI = ✅. New generation engine = ❌.
The lane is a thin **preset + orchestration** over lanes that are already sealed and
live-proven. Existing lanes' code is **untouched**, so they cannot break.

```
   V4 shell (new "Faceless" lane)  ──┐
   existing IMG/T2V/I2V/F2V lanes  ──┼──►  ONE DOOR (shared, do NOT fork)
                                     │     POST /api/flow/generate
                                     │     → make_video.start_generate
                                     ▼     + reference contract + run-ledger + compiler
                          sealed, live-proven engine (untouched)
```

---

## 3. What ALREADY EXISTS — reuse, do NOT rebuild

Every primitive Faceless needs is already in the repo and (for generation) live-proven.
Citations are `file` (`symbol`) with ~line hints; prefer the symbol if lines drift.

| Need | Reuse this (verified) |
|---|---|
| **One-door single-clip generate** | `POST /api/flow/generate` → `make_video.start_generate` (`agent/api/flow.py` ~L860, `agent/services/make_video.py` ~L280). Dashboard reaches the same door via `POST /api/flow/execute-flow-job` → `_run_manual_job_via_generate` (`flow.py` ~L3044). **Spends credits** on success (`make_video.py` ~L928). Binds to the OPEN Flow editor (fail-closed if none). |
| **Image-first (image → then animate)** | `scene` table `*_image_status` → `*_video_status` (`agent/db/schema.py` ~L185); worker defers video until the image exists (`agent/worker/processor.py` ~L190 & ~L546); `edit_scene_image` animates from the image via `IMAGE_INPUT_TYPE_BASE_IMAGE` (`agent/sdk/services/operations.py` ~L248). |
| **I2V / F2V lanes (image→video)** | Live-proven end-to-end (`.ai/status/CURRENT_STATE.md`: I2V mp4 1.51MB, F2V mp4s). |
| **Reference contract (fail-closed)** | `agent/services/flow_mode_reference_contract.py` (`validate_reference_count`, ~L45–89): F2V/FRAMES (1,2) · HYBRID (1,1) · I2V/INGREDIENTS (2,3) · T2V (0,0). |
| **Image generation** | `batchGenerateImages` + `IMAGE_INPUT_TYPE_BASE_IMAGE` / `IMAGE_INPUT_TYPE_REFERENCE` (`agent/services/flow_client.py` ~L593/599/637). |
| **Model registry (unknown fails closed)** | `agent/models.json` ~L36–40; `resolve_image_model_name` (`flow_client.py` ~L24–43). |
| **Product-truth prompt compiler** | `ugc_video_prompt_compiler_v3_scene_strategy` (`agent/services/ugc_video_prompt_compiler_service.py`); canonical compiler authority = ADR-008. |
| **Run ledger + retrieval + library** | `video_production_job`, `generated_artifact` (`schema.py`) + `GET /api/flow/artifacts` + `/api/flow/retrieved/{media_id}`. |
| **V4 shell + kit (the UI pattern)** | `dashboard/src/components/workflow/` (WorkflowStep, ResolvedChip, StoryboardStrip, QueueRow, OperatorCockpit) + `OperatorPage.tsx` V4 branch (`useV4 = new URLSearchParams(...).get("classic") !== "1"`). **Bucket 1 lanes (F2V/Hybrid/I2V/IMG) already share `OperatorPage`** — Faceless slots in the same way (handover §3.4/§4). |
| **Voice / overlay / music (for finished faceless)** | Skills: `fk-gen-narrator`, `fk-gen-tts-template`, `fk-gen-text-overlays`, `fk-gen-music`, `fk-concat` / `fk-concat-fit-narrator`. |
| **Batch fan-out** | `run_production_queue` (fires each item count=1). |

**Consequence:** the "hard parts" are done. Faceless is preset + UI + wiring.

---

## 4. What is NEW (the only things to build)

1. **A Faceless preset**: base image = product/scene image (avatar = NONE by default);
   `source_mode` = I2V/F2V single-clip; aspect/duration/count from user settings
   (USER SETTINGS ARE LAW); reference count validated by the EXISTING contract
   (`flow_mode_reference_contract.py`) — do not add a new validator.
2. **A Faceless lane in the V4 shell** — a new `mode`/lane value + V4 render branch,
   following the Bucket-1 pattern (reuse the kit + cockpit; do not reinvent).
3. **Batch faceless** — fan-out over N selected products via the existing queue.
4. *(Optional, Round 2)* wire the assembly skills (narrator → TTS → text overlays →
   music → concat-fit-narrator) into a "finished faceless clip" post-step.

---

## 5. Round plan (estimate: 1–3 rounds)

| Round | Deliverable | Definition of done |
|---|---|---|
| **R1** | Faceless lane produces **one clip**: product/scene image → I2V/F2V single-clip via the one-door, in the V4 shell. | Lane renders (default; `?classic=1` fallback preserved); one faceless clip produced **when the owner presses generate**; `scripts/verify-gate.ps1` green; no sealed path touched. |
| **R2** | **Batch** faceless (N products → N clips) + optional voice/text-overlay/music assembly via the fk-skills. | Batch fan-out runs through the existing queue; a finished faceless clip (with narration + overlay) is produced for a sample; gates green. |
| **R3** *(optional)* | Polish: faceless preset library, review board, thumbnails. | Uses `fk-review-board`, `fk-thumbnail`; owner-approved UX. |

R1 alone delivers a working faceless clip because no engine is built — it is a preset over
hardened lanes. Keep the owner in the loop before flipping the lane default and before
**anything that spends credits**.

---

## 6. Scope boundaries — DO NOT TOUCH

- **VIDEO_EXTENSION_FINAL_SEAL** (native-extend + concat, all 4 modes) — CLOSED
  (`CURRENT_STATE.md`). Faceless does not need it.
- **One-door engine internals** (`make_video.start_generate`), the negotiation brain
  (`agent_video.py`), retrieval, the artifact library — **LOCKED, additive-only, never
  rewrite**.
- **Dead DOM lane** — `extension/content-flow-dom.js` DOM-driving lanes,
  `extension/f2v-flow-queue-runner.js`, GFV2 DOM lane in `extension/background.js`.
  **Delete-only; never repair/extend/expose** (ADR-007).
- **Existing lanes' classic code** and other lanes' V4 branches — don't refactor them to
  fit Faceless.

---

## 7. Anti-patterns — do NOT copy from SESAAT

- ❌ DOM clicking / `chrome.debugger` CDP trusted-click / synthetic `ClipboardEvent('paste')`
  / drag-drop upload. The generation transport is **API-first** (ADR-007). The extension is
  authenticated transport only.
- ❌ `promptVideo1..N` / `videoScript1..N` flat schema. Use the canonical product-truth
  compiler + settings.
- ❌ Prompt tags (`##IMAGE-SET1-SCENE1##`) as identity. BOSMAX has real `media_id` /
  `operation_id`.
- ❌ `URL.createObjectURL` / Blob interception for download. Use the artifact library +
  `/api/flow/retrieved/{media_id}`.
- ❌ Hardcoded 8s. **USER SETTINGS ARE LAW** (unknown model FAILS CLOSED).
- ❌ Skip-item-after-retry. Fail closed; report honest partial.

---

## 8. Guardrails / validation gates (inherit the lockdown)

- **Surgical + additive.** No formatter noise, no unrelated files, no broad rewrites.
  Stop and ask if scope expands.
- **Register new CODE files** in `docs/MODULE_STATUS.yaml` `owned_paths` BEFORE staging —
  `scripts/mandor-check.ts` (Gate 1 of `verify-gate.ps1`) fails on any staged file not in
  `owned_paths` (see `.ai/status/*` and memory `project_mandor_check_gate`).
- **`scripts/verify-gate.ps1` must pass before reporting green** (real `npm run build` =
  `tsc -b && vite build`, vitest, backend pytest smoke, mandor-check). `tsc --noEmit` alone
  is NOT sufficient.
- **NEVER spend credits / fire generation** without the owner's explicit per-action press.
  Compile + prepare are free; the actual generate is the owner's press, and needs an
  open+warm Google Flow editor tab.
- **Restart after `.py` edits:** `scripts/start-local-agent.ps1 -ForceRestart` from repo
  root (the agent has NO `--reload`); verify `/api/local-agent/version-proof`. FE-only edits
  don't need a restart (hard-refresh picks up the new hashed bundle).
- **Commit hygiene:** checkpoint-commit each verified increment to the wip branch (this repo
  has lost staged work to a co-tenant `git` before). **Stage ONLY your files** (the tree has
  many unrelated untracked db-backups/outputs). Do NOT push/PR without owner authorization.
- **Live-verify honestly.** No runtime-green claim without runtime evidence.

---

## 9. Definition of done (project)

Faceless lane is the default in the V4 shell for its route, one-door / ADR-007 compliant,
batch works through the existing queue, `verify-gate.ps1` green, and the owner has verified
one faceless clip live. No sealed path was modified.
