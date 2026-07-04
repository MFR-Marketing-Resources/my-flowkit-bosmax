# Copy Selection & Compiler Binding Foundation V1

Status: implemented (backend + operator UI + tests).
Scope: bind an operator-selected **approved** Copy Set into the deterministic
final 9-section prompt compiler. No AI copy generation is introduced in this
round.

## Purpose

Before this change the workspace preview / final-prompt path never carried a
selected `copy_set_id`. `compile_workspace_prompt_preview` called
`compile_ugc_video_prompt(...)` **without** `copy_intelligence`, so the compiler
always fell through its own fallback chain (product landbank → claim-safe
angles). The operator could not choose a controlled, approved copywriting bundle
for a production-quality final prompt.

This foundation adds:

- a **Copy Selection UI** on the Operator page (video modes),
- explicit `copy_set_id` binding through the preview and final-prompt requests,
- a fail-closed **resolver** that converts an approved Copy Set into clean
  `copy_intelligence`,
- safe **copy-binding lineage** in the request lineage payload.

## Copy Set lifecycle

Copy Sets are owned by the existing Copy Strategy Studio service
(`agent/services/copy_set_service.py`):

```
generate → (review) → approve / reject     +  patch / regenerate
```

Statuses: `DRAFT_COPY`, `COPY_REVIEW_REQUIRED`, `COPY_APPROVED`,
`COPY_REJECTED`. Approval is explicit (approval phrase `APPROVE_COPY_SET`) and
fails closed on unsafe or incomplete copy. Any edit to an approved Copy Set drops
it back out of `COPY_APPROVED`.

## How a Copy Set binds to the final compiler

```
Operator selects an APPROVED Copy Set (UI)
        │  copy_set_id
        ▼
POST /api/workspace/ugc-video-prompt-compile   (preview)
POST /api/workspace/execution-package          (final)
        │  copy_set_id
        ▼
compile_workspace_prompt_preview(..., copy_set_id)
        │
        ▼
copy_binding_service.resolve_compiler_copy_intelligence(product_id, copy_set_id)
        │  fail-closed validation → to_compiler_copy(copy_set)
        ▼
compile_ugc_video_prompt(..., copy_intelligence=<clean copy>)   # deterministic
```

Only the fields produced by `agent.models.copy_set.to_compiler_copy` cross the
boundary into the compiler: `angle`, `copywriting_angle`, `hook`, `subhook`,
`usps`, `cta`, `formula_family`. `copy_set_id`, `status`, `provenance`, the
dedupe key, reviewer notes, and claim-review payloads **never** cross into the
compiler and therefore can never appear in the engine-facing prompt text.

## Why the final compiler stays deterministic

The final 9-section prompt is rendered by the canonical/UGC deterministic
compiler. This task only *supplies approved copy data* to that compiler via its
pre-existing `copy_intelligence` parameter. No LLM/provider call
(DeepSeek/Gemini/OpenAI/Anthropic/Qwen) is added to the final compile path.

## What happens when no Copy Set is selected

Backward compatible. When `copy_set_id` is absent:

- `copy_intelligence` is `None`, so the compiler applies its existing fallback
  (landbank → claim-safe angles),
- the response `warnings` include `COPY_SET_NOT_SELECTED`,
- lineage records `copy_binding_status: NOT_SELECTED` and
  `copy_source: landbank_fallback` — fallback copy is **never** reported as
  approved copy,
- the UI shows: *"No approved Copy Set selected. Compiler may use fallback
  copy."*

## Fail-closed validation

If an operator explicitly selects a `copy_set_id`, it must pass every check or
the request fails closed (no silent fallback substitution):

| Error code                   | HTTP | Condition                              |
| ---------------------------- | ---- | -------------------------------------- |
| `COPY_SET_NOT_FOUND`         | 404  | id does not resolve                    |
| `COPY_SET_PRODUCT_MISMATCH`  | 409  | Copy Set belongs to a different product|
| `COPY_SET_NOT_APPROVED`      | 409  | status is not `COPY_APPROVED`          |
| `COPY_SET_BINDING_FAILED`    | 422  | approved but yields no usable copy     |
| `COPY_SET_NOT_SELECTED`      | —    | warning (degraded fallback mode)       |

## Lineage (audit only, never in prompt text)

`request_lineage_payload.copy_binding`:

```json
{
  "copy_source": "selected_copy_set | landbank_fallback | claim_safe_fallback",
  "copy_binding_status": "BOUND | NOT_SELECTED | REJECTED",
  "copy_set_id": "…",             // allowed in lineage JSON only
  "copy_set_status": "COPY_APPROVED",
  "copy_set_fingerprint": "cs_…", // sha1(dedupe_key)[:16] — never the raw key
  "copy_set_angle": "…",
  "copy_set_hook_preview": "…",
  "warning": null
}
```

The raw dedupe key (which embeds the product id + copy text) is hashed to a short
opaque fingerprint before it enters lineage.

## Operator UX states (Copy Selection panel)

1. **No Copy Sets** → "Generate Copy Set" + "copywriting is not yet controlled".
2. **Copy Sets exist, none approved** → "Review and approve a Copy Set before
   production-quality final prompt".
3. **Approved Copy Set selected** → "Copy Set bound to final prompt generation".
4. **Selected Copy Set becomes invalid** (deleted / edited out of approval) → the
   panel clears the selection automatically.
5. **Deterministic note** → "Final 9-section prompt uses deterministic BOSMAX
   compiler. AI copy assist is not used in this step."

## Files

Backend:
- `agent/services/copy_binding_service.py` (new resolver + errors)
- `agent/services/workspace_execution_package_service.py` (bind + lineage)
- `agent/api/workspace_packages.py` (`copy_set_id` payload + error mapping)

Frontend:
- `dashboard/src/api/copySets.ts` (new)
- `dashboard/src/components/workspace/CopySelectionPanel.tsx` (new)
- `dashboard/src/pages/OperatorPage.tsx` (state + panel + payload binding)
- `dashboard/src/api/workspacePackages.ts`, `dashboard/src/types/index.ts`

Tests:
- `tests/unit/test_copy_binding_service.py`
- `tests/unit/test_copy_binding_workspace_integration.py`
- `tests/api/test_workspace_copy_binding_api.py`

## Known limitations

- Copy binding meaningfully affects **video modes** (T2V/HYBRID/F2V/I2V) which
  run through the UGC 9-section compiler. IMG mode compiles the image prompt from
  the approved product package; a provided `copy_set_id` is still validated
  fail-closed there but does not rewrite the image prompt.
- The Copy Selection panel implements the functional minimal action set
  (list / generate / approve / select). Full inline patch/edit/reject/regenerate
  UI is available via the API client (`patchCopySet`, `rejectCopySet`,
  `regenerateCopySet`) but is not yet surfaced as dedicated buttons.
- The dashboard has no JS test framework; frontend coverage is enforced by the
  `tsc -b && vite build` typecheck gate plus the backend contract tests.

## Next recommended phase — AI Copy Assist (NOT in this round)

A future phase may add AI Copy Assist (DeepSeek/Gemini/OpenAI/Qwen/Anthropic).
The provider must only generate **candidate Copy Sets or landbank rows** that
still flow through the existing `generate → review → approve` gate. It must
**never** replace the deterministic final 9-section compiler, and approved copy
must continue to bind exclusively through
`resolve_compiler_copy_intelligence(...)`.
