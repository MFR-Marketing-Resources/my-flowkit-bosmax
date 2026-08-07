# BUILD BRIEF — Montage (BOSMAX multi-scene operator lane)

> **Montage** = the rebrand of the owner's working name **"Infinity"**, itself the
> BOSMAX-native equivalent of SESAAT's **FLOWNITY**: one product → N discrete scenes →
> each scene generates an image → animate to a clip → **concat all clips into ONE video**.
> Renamed to avoid colliding with the sealed *native-extend* "infinite length" path (ADR-009).
> The name is a one-line swap if the owner prefers otherwise.

**Status:** NOT STARTED · greenfield · **additive**. ⛔ **BLOCKED — do Rounds 1–3
(Laluan-B hardening) BEFORE opening the lane UI.** Shipping a pretty Montage page on an
un-hardened discrete-scene path is its own way to "break the process" (silent missing
scenes, packaging drift) even though it won't break existing lanes.
**Owner:** Faris. **Authored by:** Claude Code (review/architecture).
**Build agent:** any implementation-capable AI (Codex primary per ADR-002).
**Branch:** wip branch from `wip/v4-workflow-shell`. Never push/PR without owner auth.
**Read first (SUBORDINATE to them):** `AGENTS.md` · `.ai/status/CURRENT_STATE.md` ·
`.ai/ENGINEERING_LOCKDOWN.md` · `.ai/handovers/HANDOVER-2026-08-07-v4-rollout-and-creative-config.md`.

---

## 0. TRIGGER

Paste this to start the build:

```
BUILD: MONTAGE MODULE
Read .ai/projects/MONTAGE_BUILD_BRIEF.md in full, then AGENTS.md +
.ai/status/CURRENT_STATE.md + .ai/ENGINEERING_LOCKDOWN.md. This is BLOCKED behind
Laluan-B hardening — start at Round 1 (per-scene reference policy), test-first. Reuse
full_storyboard_extend_planner's beat model; do NOT invent a promptVideoN schema. Do NOT
touch the sealed native-extend lane. Do NOT spend credits without my explicit press.
```

---

## 1. TL;DR — what to build

A **"Montage"** lane that turns ONE product into a **discrete multi-scene ad**: the
canonical storyboard planner produces beats → each beat becomes a scene (image-first:
generate scene image → animate to a short clip) → all clips **concatenate into one video**
→ voiceover/overlay/music.

This is BOSMAX's **"Laluan-B" (discrete-scene) path**. It is distinct from the sealed
**"Laluan-A" native-extend** path (one continuous video chained in 8s blocks). Laluan-B
already exists but is **less hardened** — its "all scenes ready" logic currently lives in
skill code, not a fail-closed service. Montage = **harden Laluan-B, then surface it**.

---

## 2. The golden rule (why this is safe)

**Separate UI lane, SHARED engine.** New lane UI = ✅. New generation engine = ❌.
Reuse the one-door for each scene's clip, and **reuse the canonical storyboard planner for
the story** — do NOT recreate SESAAT's flat `promptVideo1..N` schema (that is a downgrade).

---

## 3. What ALREADY EXISTS — reuse, do NOT rebuild

| Need | Reuse this (verified) | Notes |
|---|---|---|
| **Story brain (beats/dialogue/continuity)** | `agent/services/full_storyboard_extend_planner.py`: `FullStoryPlan`, `StoryBeat`, `DialogueUtterance`, `FullDialoguePlan`, `BlockAllocation`, `ContinuityState` (~L42–146) + `validate_planner_result` (~L1137). | The hard part is DONE. Montage routes beats to discrete scenes; do NOT invent promptVideoN. |
| **Per-scene image→video** | `scene` table `*_image_status`→`*_video_status` (`schema.py` ~L185); `processor.py` (~L190/546); `edit_scene_image` (`operations.py` ~L248). | The image-first pipeline for one scene. |
| **One-door single clip (per scene)** | `POST /api/flow/generate` → `make_video.start_generate` (`flow.py` ~L860, `make_video.py` ~L280). | Same door Faceless uses. Spends credits. |
| **Reference contract (per-mode, fail-closed)** | `flow_mode_reference_contract.py` (~L45–89). | Round 1 extends this to per-scene (see §4). |
| **Run ledger (per-block, resumable)** | `extend_lineage` (per-block, `polling_state` incl. `BLOCKED`, `idempotency_key`), `video_production_job`, `video_job_side_effect` (`schema.py` ~L2083–2160); orchestrator `video_production_orchestrator.py`. | Already exists (was ChatGPT's "P0-3" — redundant to rebuild). If an image-first phase vocab is wanted, EXTEND the enum, don't add a table. |
| **Concat / assembly preflight (fail-closed)** | `preflight_segment_durations` (`agent/services/google_flow_final_timeline_runtime.py` ~L164–212): `SEGMENT_COUNT_MISMATCH` / `SEGMENT_DURATION_*`. | Round 3 extends this to the discrete-scene concat path (see §4). |
| **V4 shell + kit** | `dashboard/src/components/workflow/` + `OperatorPage.tsx` V4 branch. | Round 4 UI. Montage is closer to handover **Bucket 3** (bespoke multi-scene) — apply the design LANGUAGE, keep its own IA; don't force it into the single-shot shell. |
| **Voice/overlay/music/concat** | `fk-gen-narrator`, `fk-gen-tts-template`, `fk-gen-text-overlays`, `fk-gen-music`, `fk-concat` / `fk-concat-fit-narrator`. | Finished-video assembly. |

---

## 4. What is NEW — the 3 hardening gaps (verified against code)

These are the genuine gaps found in the 2026-08-07 forensic map. Montage is BLOCKED until
Rounds 1–3 close them.

1. **Per-scene reference policy** *(the cleanest real gap)*. Today reference enforcement is
   **per-mode at the job level** only (`flow_mode_reference_contract.py`) — there is **no**
   per-scene declaration (`reference_policy` / `image_generation_required` /
   `video_generation_required` = **0 matches** in the codebase). Add a small per-scene/
   per-beat descriptor with a `SCENE_REFERENCE_POLICY` enum
   (`NONE / PRODUCT_ANCHOR / START_FRAME / START_END_FRAMES / AVATAR_PRODUCT /
   INGREDIENT_REFERENCES / INHERIT_PREVIOUS_CLIP`), **validated against the EXISTING
   contract** (no new enforcement engine). This is the correct generalization of SESAAT's
   crude "last scene only gets product" rule — each scene declares its own product-truth
   need, so a product shown in scene 1 is also locked → **no packaging drift** (BOSMAX's
   north star).
2. **Scene execution routing.** `BlockAllocation` carries no routing flags. Add the per-scene
   choice of (A) direct-video / (B) image-first / (C) inherit-previous, dispatched onto the
   EXISTING `scene` table/worker — not a new pipeline.
3. **Assembly readiness gate for the discrete-scene concat path.** Extend
   `preflight_segment_durations` (or add a sibling) so that, before concat, it fails closed
   with a named `BLOCKED_INCOMPLETE_SCENE_SET` when any scene whose policy demands product
   truth did not bind a product `media_id`, or any mandatory scene/dialogue block is missing —
   not just count+duration. Never silently assemble a partial set.

---

## 5. Round plan (estimate: 3–5 rounds)

| Round | Deliverable | Definition of done |
|---|---|---|
| **R1** | Per-scene **reference policy** descriptor + `SCENE_REFERENCE_POLICY` enum, validated by the existing contract. Test-first. | Unit tests: each scene declares + validates its refs; fail-closed on violation; existing per-mode contract unchanged. |
| **R2** | **Scene execution routing** (beat → image-first/direct on the existing `scene` table/worker). | A storyboard's beats route to discrete scenes; each scene's image→video runs; no new engine. |
| **R3** | **Assembly readiness gate** for the discrete concat path + `BLOCKED_INCOMPLETE_SCENE_SET`; reference/dialogue-aware. | Concat refuses a partial/mis-referenced set (fail-closed test); a complete set assembles. |
| **R4** | **Montage lane UI** in the V4 shell (Bucket-3 style) + wiring storyboard→N-scene + voice/overlay/music assembly. | One product → multi-scene montage produced end-to-end **when the owner presses generate**; `verify-gate.ps1` green. |
| **R5** *(optional)* | Scale hardening: perceptual dedup, throughput pacing, review board. | Owner-approved for mass production. |

Do R1–R3 (backend, test-first) **before** R4 (UI). Keep the owner in the loop before any
credit-spending run.

---

## 6. Scope boundaries — DO NOT TOUCH

- **Laluan-A / VIDEO_EXTENSION_FINAL_SEAL** (native-extend + concat) — CLOSED. Montage is a
  **separate** discrete-scene path; do NOT modify the sealed continuous-timeline path or its
  `preflight_segment_durations` in a way that changes Laluan-A behavior (add a sibling/branch
  for the discrete path instead).
- **One-door engine internals**, negotiation brain, retrieval, artifact library — LOCKED,
  additive-only.
- **Dead DOM lane** (`content-flow-dom.js`, `f2v-flow-queue-runner.js`, GFV2) — delete-only
  (ADR-007).

---

## 7. Anti-patterns — do NOT copy from SESAAT

Same list as Faceless (§7 there), **plus the Montage-specific one**:

- ❌ **Do NOT recreate `promptVideo1..N` / `videoScript1..N`.** Reuse
  `full_storyboard_extend_planner`'s beat/dialogue model. Recreating the flat schema is a
  schema **downgrade** and throws away continuity/seam/dialogue-slice authority.
- ❌ Do NOT take SESAAT's "last scene only = product reference" as a global rule — that is the
  exact packaging-drift trap. Per-scene policy (R1) is the fix.
- (also) no DOM/CDP, no prompt tags, no Blob hacks, no hardcoded 8s, no skip-scene-after-retry.

---

## 8. Guardrails / validation gates

Identical to `FACELESS_VIDEO_BUILD_BRIEF.md §8` (surgical/additive · register new files in
`docs/MODULE_STATUS.yaml` before staging · `verify-gate.ps1` before green · NEVER spend
credits without owner press · restart agent after `.py` edits · checkpoint-commit to wip ·
stage only your files · live-verify honestly).

---

## 9. Definition of done (project)

Laluan-B is hardened (per-scene reference policy + scene routing + fail-closed assembly gate,
all test-covered), the Montage lane exists in the V4 shell, one product → a coherent
multi-scene montage is produced end-to-end and owner-verified live, `verify-gate.ps1` is
green, and the sealed native-extend path was not modified.
