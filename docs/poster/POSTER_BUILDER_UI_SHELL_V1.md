# Poster Builder UI Shell V1

## Purpose

This module is the operator-facing bridge between **PR #232 Poster Readiness Gate** and the future poster generator. It does not generate posters, prompts, or images.

## Readiness consumption

On product selection the UI calls:

```http
GET /api/products/{product_id}/poster-readiness
```

The dashboard **does not** infer readiness. Rendering uses API fields only (`poster_status`, `generation_allowed`, `blockers`, `repair_actions`, etc.).

## Status handling

| API status | Operator label | Builder shell | Generate |
|------------|----------------|---------------|----------|
| `POSTER_READY` | Ready | Full form | Disabled — generator not implemented |
| `POSTER_READY_RESTRICTED` | Restricted Ready | Full + restricted badge + rules | Disabled — restricted generator not implemented |
| `POSTER_REPAIR_REQUIRED` | Repair Required | Hidden | Disabled — complete repairs |
| `POSTER_PREVIEW_ONLY` | Preview Only | Preview/diagnostic form | Disabled — production off |
| `POSTER_BLOCKED` | Blocked | Hidden + human review panel | Disabled — blocked |

## Repair action center

When the API returns `repair_actions`, the UI lists:

- label, action code, severity
- human approval / auto-executable / manual review flags
- recommended endpoint (copy-only in V1)
- expected status after success / if no other blockers
- notes

Mutating repair endpoints are **not** auto-executed in this PR.

## Poster builder shell fields

Local draft state only (JSON preview panel):

- Poster Objective, Poster Type, Visual Route, Human Presence Mode
- Frame Ratio, Language, Text Density
- Angle, Hook, Subhook, USP 1–3, CTA
- Notes / Operator Instruction

## Intentionally disabled

- Generate poster (all statuses)
- Image generation / external engines
- Product mutation during readiness check
- Auto claim clearance

## Future generator integration

A later PR should:

1. Re-fetch readiness before generate.
2. Refuse if `generation_allowed` is false.
3. Apply restricted copy rules when `poster_status === POSTER_READY_RESTRICTED`.
4. Map draft fields into the poster prompt contract.

## Route

`/creative/poster-builder` — nav entry **Poster Builder** under ASSETS.

## Target products (PR #231 IDs)

Quick-select buttons load catalog rows when present; readiness always comes from the API.

- Bosmax Oil / Herbs → expect `POSTER_REPAIR_REQUIRED` + `CLAIM_RISK_HIGH` when DB matches audit baseline.
- Minyak Warisan → expect `POSTER_READY` when DB matches baseline; UI shows actual API status if stricter.

## Tests

```bash
cd dashboard && npm test
```

Logic tests: `src/poster/posterBuilderUi.test.ts`  
Page smoke: `src/pages/PosterBuilderPage.test.tsx`