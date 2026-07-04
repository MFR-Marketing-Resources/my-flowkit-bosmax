# Copy Fallback — Explicit Confirmation V1

Status: implemented (backend-enforced + operator UI). Builds on
[COPY_SELECTION_AND_COMPILER_BINDING_FOUNDATION_V1](COPY_SELECTION_AND_COMPILER_BINDING_FOUNDATION_V1.md).

## Purpose

The V1 foundation let the operator select an approved Copy Set, but **Generate
Final Prompt** could still proceed with **warning-only** fallback when nothing was
selected — too easy to bypass controlled copy selection. This change makes
production final-prompt generation **intentional** without hard-gating the whole
workflow.

## Policy

| Action | No Copy Set selected | Approved Copy Set selected |
| --- | --- | --- |
| **Load Package Preview** | ✅ runs, warning-only (`COPY_SET_NOT_SELECTED`) — unchanged | ✅ binds selected copy |
| **Generate Final Prompt** | ⛔ fails closed unless `copy_fallback_confirmed = true` | ✅ runs, no confirmation needed |

- Preview is **never** gated — it stays warning-only.
- Final generation with no `copy_set_id` **and** no `copy_fallback_confirmed`
  fails closed: `COPY_SET_FALLBACK_CONFIRMATION_REQUIRED` (HTTP 409).
- A provided `copy_set_id` never needs confirmation — it is validated fail-closed
  by the resolver (invalid → 404/409, **not** bypassable via confirmation).

## Why this is not a hard gate

Fallback copy (product landbank / claim-safe angles) is still legitimate for
degraded/manual operation. Hard-blocking all fallback would break backward
compatibility and legitimate workflows. Instead we require a single explicit,
audited operator confirmation for the **saved final package** only.

## Backend is the source of truth

The confirmation is enforced in `create_workspace_execution_package(...)` —
the FIRST check, before any package/compile work:

```python
if not copy_set_id and not copy_fallback_confirmed:
    raise CopyBindingError("COPY_SET_FALLBACK_CONFIRMATION_REQUIRED", status_code=409, detail=...)
```

The frontend modal/gate is UX only; a scripted/API caller cannot skip it.

## Lineage (audit only — never in prompt text)

Fallback is still recorded as fallback — confirmation is **separate** metadata,
never relabels fallback as approved copy:

```json
"copy_binding": {
  "copy_binding_status": "NOT_SELECTED",
  "copy_source": "landbank_fallback",
  "warning": "COPY_SET_NOT_SELECTED",
  "copy_fallback_confirmed": true,
  "copy_fallback_confirmation_required": true,
  "copy_fallback_confirmation_source": "operator",
  "copy_fallback_policy": "explicit_confirmation_v1"
}
```

The confirmation block is added **only** when fallback was explicitly confirmed
(absent when a Copy Set is bound). None of it enters the engine-facing prompt
text.

## Operator UX (OperatorPage, video modes)

- State line above Generate: "Approved Copy Set bound to final prompt generation."
  vs "No approved Copy Set selected. Generate Final Prompt requires fallback
  confirmation."
- Pressing **Generate Final Prompt** with no Copy Set opens an explicit gate:
  *"No approved Copy Set selected. Generate Final Prompt will use fallback copy
  from product landbank / claim-safe angles. This fallback is not approved Copy
  Set copy. Continue with fallback?"* → **Confirm fallback and continue** /
  **Cancel and select / approve Copy Set**.
- Confirm calls the final API with `copy_set_id: null, copy_fallback_confirmed: true`.
- After generation, the returned `copy_binding` status is shown (BOUND, or
  "Fallback copy — operator-confirmed").

## Guarantees preserved

- Final 9-section compiler stays **deterministic** — only approved copy data (or
  the existing landbank/claim-safe fallback) feeds it via `copy_intelligence`.
- **No AI provider execution** anywhere in this path.
- Preview behavior unchanged.

## Files

Backend: `agent/services/copy_binding_service.py` (error/constants),
`agent/services/workspace_execution_package_service.py` (gate + lineage stamp),
`agent/api/workspace_packages.py` (`copy_fallback_confirmed` field + threading).
Frontend: `dashboard/src/pages/OperatorPage.tsx` (confirmation gate + state),
`dashboard/src/api/workspacePackages.ts`, `dashboard/src/types/index.ts`.
Tests: `tests/unit/test_copy_binding_workspace_integration.py`,
`tests/api/test_workspace_copy_binding_api.py`,
`tests/unit/test_workspace_execution_package_service.py` (fallback-confirmed on
existing no-Copy-Set calls).

## Known limitations

- Applies to video-mode final packages via the workspace execution-package route.
  The IMG execution lane and F2V/I2V generation-package routes
  (`createF2VGenerationPackage`/`createI2VGenerationPackage`) are separate and not
  re-gated here — those save from an already-generated execution package, so the
  confirmation was already enforced upstream when that package was created.
- Confirmation is a single boolean intent, not a per-reason capture.
