# BOSMAX Canva Product Cutout Workflow

Status: `IN_PROGRESS` implementation in the `workspace` domain. This document is the SSOT for Canva-assisted cutouts; it does not authorize full-catalog processing.

The workflow is an assisted quality lane around the governed Smart Registration visual authority delivered by PR #683. Canva is used for operator-controlled isolation. BOSMAX owns identity, dimensions, durable state, alpha verification, provenance, fallback, and human approval.

## Scope and non-negotiables

- The canonical source is resolved from the same BOSMAX product row and identified by SHA-256 plus dimensions before Canva work begins.
- The existing `product_visual_onboarding` manual lane remains the cutout authority. Do not create a second approval or canonical-media path.
- Every Canva result is `PENDING_HUMAN_REVIEW`. No checkbox, preflight result, Canva status, or machine check can auto-approve Product Truth.
- A white RGB PNG is not a transparent cutout. A valid result must contain an alpha-bearing PNG with transparent pixels and visible product pixels.
- The output canvas must preserve the exact source width and height. BOSMAX does not resize, crop, or silently repair a Canva export.
- No Canva cookies, session tokens, passwords, or provider secrets are written to the database. Only non-secret operator evidence is persisted.
- The workflow is bounded and resumable. It is not permission to process the full catalog or to resume the historical Python auto-cutout run.

## Capability boundary

| Boundary | BOSMAX contract |
| --- | --- |
| `AUTOMATABLE_IN_BOSMAX` | Resolve the same-product source; capture SHA/dimensions; persist state; verify PNG format/alpha/dimensions with Pillow; register the result in the existing manual lane; expose review/fallback state. |
| `AUTOMATABLE_VIA_LOCAL_BROWSER_CONTROLLER` | Open an operator-provided Canva design; observe the Canva UI; assist with a download. A proven controller is not currently wired into this lane. |
| `USER_ACTION_REQUIRED` | Canva login/session; Pro entitlement; Magic Grab, Background Remover, or Magic Layers operation; visual identity review; explicit Exact Cutout approval. |

The UI and API must surface this boundary. They must not claim to have clicked Magic Grab, edited a page, or exported a transparent PNG when the operator has not supplied evidence.

## Canva preflight gate

Preflight happens before editing or bulk queue work:

1. Confirm the operator is logged in to Canva.
2. Inspect which Canva functions are available: Magic Grab, Background Remover, and Magic Layers.
3. Capture the exact source dimensions from BOSMAX.
4. Confirm that transparent PNG export is available.

If transparent export is locked behind a crown/Pro entitlement, persist `CANVA_PRO_REQUIRED` and stop before editing. The bulk queue uses `BLOCKED_CANVA_PRO_REQUIRED`; it does not start hundreds of designs that cannot produce the required artifact.

The preflight ledger stores only statuses such as `READY`, `UNAVAILABLE`, `UNKNOWN`, `PRO_REQUIRED`, or `USER_ACTION_REQUIRED`, plus a non-secret design ID/URL when supplied.

## Escalation ladder

### 1. Magic Grab

Use when the Canva UI exposes Magic Grab and isolation quality is acceptable:

1. Load the exact BOSMAX canonical product image.
2. Invoke Magic Grab in the real Canva UI.
3. Inspect the complete product: cap, body, label, logo, edges, and geometry.
4. Remove unrelated scene/background material.
5. If the page cannot become transparent, move only the isolated product to a clean same-size canvas.

This is the preferred method when the result preserves product identity.

### 2. Background Remover

Use when Magic Grab is unavailable or the isolation is poor:

1. Select the exact product image.
2. Run Background Remover.
3. Inspect the full product and all legitimate pixels.
4. Restore or retry when the cap, label, logo, edge, or body has been removed.

Canva reporting “removed” is not evidence of product correctness.

### 3. Magic Layers

Use for promotional images with text, decorations, multiple objects, or scene fragments:

1. Invoke Magic Layers/image-to-design in the actual Canva UI.
2. Identify every legitimate product element.
3. Preserve product pixels and delete promotional text, CTA, decorative objects, unrelated food/props, and background fragments.
4. Never delete a legitimate product component.

The fixed-page/root background can be non-deletable through MCP. That is a tooling limitation, not a reason to delete product evidence. Use the actual Canva UI or the clean-canvas method.

### 4. Clean same-size canvas

When the original Magic Layers page cannot become transparent:

1. Create a clean Canva design with exactly the source dimensions.
2. Transfer only the isolated product element(s).
3. Preserve scale and aspect ratio; do not crop or distort.

Example: an `800x800` source requires an `800x800` clean design.

## Export and BOSMAX handoff

Export from Canva as `PNG` with `Transparent Background = ON`. Then upload the file through `Upload Canva PNG → Manual Review` in the Product Visual Readiness panel.

BOSMAX performs these checks before persistence:

- PNG format;
- exact source width and height;
- actual alpha-bearing image mode or transparency metadata;
- at least one transparent pixel;
- at least one visible product pixel.

On success the handoff is:

```text
Canva PNG
  -> VERIFYING_ALPHA
  -> existing upload_manual_product_cutout()
  -> Product Truth candidate (source_kind=USER_UPLOAD,
     provenance.source=CANVA_MAGIC_GRAB|CANVA_BG_REMOVER|CANVA_MAGIC_LAYERS)
  -> PENDING_HUMAN_REVIEW
  -> existing explicit approval gate
  -> APPROVED / exact commerce enabled
```

`USER_UPLOAD` remains the underlying PR #683 source-kind contract so history, replacement, reject, and fallback semantics remain compatible. The exact Canva method is preserved in `provenance.source`, `cutout_provenance`, and `canva_provenance_source`.

On failure, the Canva ledger becomes `FAILED` with a stable error code. The same-product reference remains available as `VISUAL_GROUNDING_READY_FALLBACK`; Exact Commerce may remain `CUTOUT_REQUIRED`.

## State machine

The durable per-product state machine is:

```text
NOT_STARTED
  -> PREFLIGHT
  -> CANVA_PRO_REQUIRED                 (transparent export unavailable)
  -> OPENING_CANVA
  -> MAGIC_GRAB | BACKGROUND_REMOVER | MAGIC_LAYERS
  -> CLEAN_CANVAS
  -> READY_TO_EXPORT
  -> EXPORTING
  -> VERIFYING_ALPHA
  -> CUTOUT_READY
  -> PENDING_HUMAN_REVIEW
  -> APPROVED

Any active operator stage may -> PAUSED or FAILED.
PAUSED may resume at the persisted stage.
FAILED may start a new bounded attempt.
CANCELLED is terminal for a cancelled bulk item/run.
```

Persisted per-product evidence includes:

- `product_id` and a workflow ID;
- source SHA-256 and source width/height;
- Canva method, non-secret design ID/URL;
- current stage, attempt count, last error code/message;
- started/updated timestamps;
- output path/SHA-256 and output dimensions after local handoff;
- `alpha_verified`;
- human review status;
- Canva provenance source.

The additive tables are `canva_cutout_workflow`, `canva_cutout_bulk_run`, and `canva_cutout_bulk_item`. They do not replace `product_cutout_preparation` or `product_visual_truth_lock`.

## Per-product operation

The `Canva Cutout` button is available in Smart Registration → Semua Produk rows and the Product Visual Readiness detail panel when a trusted same-product source is available. It is independent of any bulk run.

The button:

1. resolves and fingerprints the canonical source;
2. creates or resumes the product ledger at `PREFLIGHT`;
3. lets the operator record Canva capability preflight and a design reference;
4. exposes the non-secret design link when supplied;
5. accepts the exported PNG only after the operator has performed the Canva UI work;
6. hands the result to the existing manual candidate/review/approval lane.

`Approve Exact Cutout` always means “approve the currently active candidate after inspecting identity, label/logo, geometry, and scale.” It applies equally to a Canva handoff and a normal manual upload; it never means “approve the auto candidate without review.”

## Resumable bulk operation

`Prepare Canva Cutouts` is optional and preview-first:

1. preview eligible IDs and counts;
2. preserve priority IDs first, then the canonical preview order;
3. require explicit confirmation and a fresh preview digest;
4. default to a bounded batch of three, with an API maximum of 25;
5. persist each item and the run status;
6. pause/resume/cancel from durable DB state;
7. allow a per-product bypass without cancelling the remaining queue.

The bulk run is an operator queue, not a fake Canva worker. Unknown preflight produces `PAUSED` with `CANVA_PREFLIGHT_REQUIRED`; a Pro-locked transparent export produces `BLOCKED_CANVA_PRO_REQUIRED`. A per-product `Canva Cutout` action remains usable while the queue is slow, paused, blocked, or cancelled.

## Review, fallback, and aliases

- Every candidate remains pending until the existing Product Truth approval route records explicit reviewer identity, note, identity confirmation, label/logo confirmation, and geometry/scale confirmation.
- Approval mirrors the Canva ledger to `APPROVED` only after Product Truth itself succeeds.
- Rejection/failure keeps the candidate history and leaves the trusted same-product fallback available.
- Archived products, purged aliases, merged/tombstoned aliases, and test fixtures are excluded from preview and blocked at the per-product start boundary.
- No remote image is silently downloaded by a readiness GET or a bulk preview.

## Bounded proof rule

Before any full-catalog decision, prove the reusable workflow on no more than three representative products:

1. simple isolated packaging;
2. complex promotional image with text/decorations;
3. difficult edge/transparent/irregular product.

For each product require a real transparent PNG, alpha verification, same-size metadata, a BOSMAX manual-lane receipt, `PENDING_HUMAN_REVIEW`, and preserved same-product fallback. Do not auto-approve. If transparent export entitlement is unavailable, report `PASS_WITH_CANVA_PRO_REQUIRED` and do not claim factory readiness.

The current bounded local receipt covers the preflight stop only: `test_bounded_three_product_preflight_stops_at_canva_pro_gate` exercises promotional, simple-label, and irregular-shape representatives and records `CANVA_PRO_REQUIRED` for all three when transparent export is Pro-gated. No PNG output, alpha receipt, or human approval is claimed from that blocked run; those stages remain intentionally unexecuted until entitlement is proven.
