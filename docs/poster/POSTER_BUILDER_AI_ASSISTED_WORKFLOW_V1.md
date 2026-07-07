# Poster Builder — AI-assisted copy workflow (v1)

Design authority: `Hal berkaitan poster modul.txt` — **copy bank first, AI assist second, manual override always available**.

## Root cause (blank manual workflow)

PR #254 shipped a readiness-gated **prompt draft** engine with a single **manual field shell**. Operators had to type angle, hook, subhook, USP, and CTA before any system help — matching a skeleton prompt form, not the agreed **3-lane** production UX (Auto / Guided / Manual).

## Architecture (this PR)

| Layer | Role |
|--------|------|
| **Approved / draft copy sets** | `list_copy_sets_for_product` → kits tagged `APPROVED_COPY_SET` / `DRAFT_COPY_SET` |
| **AI assist** | Ephemeral kits via `ai_copy_provider_adapter` + `ai_copy_assist_service._build_brief` (no auto-approve, no DB write) |
| **Fallback templates** | Safe generic kits when bank + AI are insufficient |
| **Readiness gate** | Same `PosterReadinessService` as PR #254 |
| **Prompt package** | Unchanged `POST /api/poster/prompt-draft` after kit selection |

### API

`POST /api/poster/copy-recommendations`

Request: `product_id`, optional `poster_objective`, `poster_type`, `frame_ratio`, `language`, visual defaults, `refresh_ai`.

Response: `recommendations[]` (kits with `source`, `status`, copy + visual defaults), `generation_allowed`, `poster_status`, `warnings`, `repair_actions`.

### UX (`/creative/poster-builder`)

1. Select product → readiness loads.
2. **Working mode** (default **Auto / Quick Start**):
   - **Auto**: minimum fields + recommendation cards → Select kit / Use for prompt draft.
   - **Guided**: angle → hook → subhook/USP/CTA from kit pool.
   - **Manual Expert**: full PR #254 field shell.
3. **Prompt package preview** via existing API.
4. **Image generation**: handoff section only — not enabled (see below).

### Safety

- `scan_copy_safety` + poster `UNSAFE_CLAIM_TERMS` on operator copy before kits are returned.
- `POSTER_REPAIR_REQUIRED` / `POSTER_BLOCKED`: no usable kits for generation.
- AI kits are always `AI_CANDIDATE` / `candidate`.

### Bulk production (future)

Per product: readiness → `copy-recommendations` → operator picks kit → `prompt-draft` → (later) gated image queue. This PR does not implement bulk queue.

### Manual verification

1. `main` + agent running; open `/creative/poster-builder?product_id=<ready-uuid>`.
2. Confirm **Working mode** strip and **Auto** panel (not blank hook fields first).
3. Click **Generate / Refresh recommendations** — cards show `source` + `status`.
4. **Select kit** — draft JSON preview fills hook/USP/CTA.
5. **Use for prompt draft** — preview panel shows `DRAFT_READY` or blocked message.
6. Switch **Manual Expert** — all fields editable; prompt draft still works.
7. Repair-required product — repair center visible; working modes hidden.

### Runtime stability (flicker prevention)

- `loadRecommendations` does **not** depend on live `draft` (uses `draftRef` + optional snapshot) so draft/Flow Mirror edits do not retrigger auto-fetch loops.
- Auto recommendations load **once per product** (`autoRecLoadedProductRef`); manual **Refresh** passes current draft explicitly.
- `loadReadiness` clears shell state only when **product id** changes; recheck keeps UI mounted.
- URL `product_id` sync sets `selectedProduct` only when id changes.

### Atomic “Use for prompt draft”

Auto mode **Use for prompt draft** calls `handleUseKitForPromptDraft(kit)`, which builds `nextDraft = kitToDraft(kit, …)` and passes it directly to `handlePromptDraft(nextDraft)`. It does **not** rely on stale React state after `setDraft`.

### Flow Mirror Settings / Output Control

Section **Flow Mirror Settings** (all modes when shell is visible):

- **Aspect Ratio:** 9:16, 1:1, 16:9, 4:3, 3:4 — synced with `draft.frame_ratio` (single source; kit select updates both).
- **Count:** 1x–4x — handoff metadata only; no image API calls.
- **Image Model:** from shared `useImageGenSettings()` / `/api/img-factory/image-gen-settings` (same SSOT as Avatar Registry, IMG Fastlane). Default **Nano Banana 2**.

Captured in Draft JSON preview as `flow_mirror_settings` and in the disabled handoff block. Backend prompt-draft API unchanged; persistence to server is future work.

Future path: gated poster image route reads prompt package + flow mirror settings + explicit operator click (Google Flow / Nano Banana family).

### Image generation status

**Not implemented; handoff-ready only.** Avatar/Scene Registry use `/api/ai/generate-image` with explicit clicks. Poster module stops at prompt package until a dedicated gated poster image route is designed (no auto credit burn).

### Tests

```bash
python -m pytest tests/unit/test_poster_copy_recommendation_service.py tests/api/test_poster_copy_recommendation_api.py tests/unit/test_poster_prompt_draft_service.py tests/api/test_poster_prompt_draft_api.py tests/unit/test_poster_readiness_service.py tests/api/test_poster_readiness_api.py -q
cd dashboard && npm test && npm run build
python scripts/verify_poster_target_products.py
```