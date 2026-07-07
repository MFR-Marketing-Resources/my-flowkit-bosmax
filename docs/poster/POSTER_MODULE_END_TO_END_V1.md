# Poster Module End-to-End V1 (Copy → Final Prompt)

## Purpose

This document describes the **poster prompt module** layered on top of merged baselines:

- PR #231 — Product Truth Poster Readiness Audit V3
- PR #232 — Poster Readiness Gate + Repair Action Contract (`GET /api/products/{product_id}/poster-readiness`)
- PR #253 — Poster Builder UI Shell (`/creative/poster-builder`)

This V1 workflow takes an operator from **product selection → readiness gate → copy fields → final poster prompt package preview**. It does **not** execute live image generation.

## End-to-end flow

1. **Product selection** — Searchable catalog on Poster Builder (no duplicate catalog logic).
2. **Readiness gate** — Always `GET /api/products/{product_id}/poster-readiness` before enabling prompt draft. UI does not infer readiness.
3. **Copy selection / draft** — Operator fills poster objective, type, visual route, human presence, frame ratio, language, text density, angle, hook, subhook, USPs, CTA, operator notes. No fake approved copy bank; manual input only unless future copy-bank APIs are wired.
4. **Prompt draft** — `POST /api/poster/prompt-draft` assembles a deterministic package from readiness + product truth + draft fields.
5. **Preview** — UI shows `PosterPromptPackagePreview` (poster prompt, negative prompt, JSON package).
6. **Save / export** — Not persisted in V1 unless a separate safe draft-store API is added later. Package is returned in the API response for operator copy/handoff.

## Readiness → behavior matrix

| `poster_status` | Builder shell | Prompt draft | Image generation |
|-----------------|---------------|--------------|------------------|
| `POSTER_READY` | Full | Enabled (`DRAFT_READY`) | Disabled |
| `POSTER_READY_RESTRICTED` | Restricted | Enabled with safety guardrails | Disabled |
| `POSTER_PREVIEW_ONLY` | Preview/diagnostic | Enabled (`PREVIEW_ONLY`) | Disabled |
| `POSTER_REPAIR_REQUIRED` | Hidden | Disabled; repair actions | Disabled |
| `POSTER_BLOCKED` | Hidden | Disabled; human review | Disabled |

## API contract

### `POST /api/poster/prompt-draft`

Request body matches poster builder draft fields plus `product_id`.

Response highlights:

- `prompt_package_status`: `DRAFT_READY` | `PREVIEW_ONLY` | `BLOCKED` | `REPAIR_REQUIRED`
- `poster_prompt`, `negative_prompt`, `copy_layout`, `product_truth_lock`, `safety_guardrails`
- `repair_actions` / `blocked_reasons` when generation is not allowed
- `readiness_meta` — snapshot of readiness evaluation (read-only)

Validation:

- Critical fields required when draft generation is allowed: objective, type, visual route, frame ratio, language, angle, hook, CTA.
- Restricted-safe mode scans hook/subhook/USP/CTA/notes for obvious claim-risk terms (deterministic list; not a full compliance engine).

## Restricted-safe handling

When readiness is `POSTER_READY_RESTRICTED`, the assembled prompt includes explicit guardrails:

- No cure/treat/heal/disease/guaranteed relief/before-after/fake proof
- Lifestyle, heritage, portability, product-size angles only

Unsafe wording in operator copy is rejected with HTTP 422.

## Out of scope (V1)

- Live image generation (Google Flow, Grok, FAL, etc.)
- Product row mutation, auto claim clearance, auto repair execution
- Hardcoded product shortcuts in production UI
- Invented approved copy bank data

## Future image generation plug-in

When an engine is added:

1. Keep readiness gate as mandatory pre-check.
2. Consume `poster_prompt` + `negative_prompt` from this package only after `prompt_package_status` is `DRAFT_READY` (or approved restricted/preview policy).
3. Keep a separate explicit “run engine” action with credits/approval; do not enable from this V1 shell automatically.

## Manual verification

1. Open `/creative/poster-builder?product_id=<uuid>`.
2. Confirm readiness card loads from API.
3. Fill copy fields; click **Generate poster prompt draft** when enabled.
4. Confirm preview panel shows prompt + negative prompt.
5. Confirm **Generate poster (image)** stays disabled.

Example product IDs (tests/docs only):

- Bosmax Oil 10 ML: `b460ffbd-7d9d-4f6b-a570-0e9b1056439a`
- Bosmax Herbs 5 ML: `90349f8c-9e14-4efe-988e-76ec60ea31f4`
- Minyak Warisan 25ml: `6483d624-a03d-4933-9bba-6ca2e5f7b6fd`