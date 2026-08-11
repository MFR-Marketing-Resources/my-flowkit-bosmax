# Canva Cutout Operator Runbook

Use this runbook for one product or a bounded Canva queue. It is an operator playbook, not permission to process the whole catalog.

## 1. Preflight commands and checks

From the isolated/current repository checkout:

```powershell
git fetch origin
git rev-parse origin/main
python -m pytest tests/unit/test_canva_cutout_workflow_service.py tests/api/test_canva_cutout_workflow_api.py -q
```

Confirm the runtime is using the canonical BOSMAX checkout and DB:

- repository: `C:\Users\USER\Desktop\_ref_flowkit`;
- DB: `C:\Users\USER\Desktop\_ref_flowkit\flow_agent.db`;
- extension: `C:\Users\USER\Desktop\_ref_flowkit\extension`;
- never substitute the SESAAT profile/extension or a temporary DB as delivery proof.

Do not restart Chrome, the extension, or runtime merely to rediscover Canva capability. A runtime restart is a separate deployment decision after an accepted merge.

## 2. Start one product

1. Open Smart Registration → Semua Produk or the Product Visual Readiness detail panel.
2. Confirm the product is active and the reference is the same product.
3. Click `Canva Cutout`.
4. Confirm the displayed source dimensions and the persisted source identity.
5. Do not continue if the source is missing, an archived/purged alias, or a test fixture.

The first state is `PREFLIGHT`. No Canva editing is represented as complete at this point.

## 3. Canva login and entitlement check

In the real Canva UI, confirm:

- the operator is logged in;
- the intended workspace is open;
- Magic Grab availability;
- Background Remover availability;
- Magic Layers availability;
- transparent PNG export is available.

Record the observed statuses in the workflow panel. If transparent export displays a crown/Pro lock, record `PRO_REQUIRED`. BOSMAX moves to `CANVA_PRO_REQUIRED` and must not begin expensive editing.

Known account evidence: the previously tested Canva session could use BG Remover in the UI, but transparent export was Pro-gated. Treat this as account/session evidence, not a universal Canva product claim; re-check the live account.

## 4. Magic Grab procedure

Use Magic Grab first when available:

1. load the exact canonical product image;
2. isolate the complete product;
3. inspect cap, body, label, logo, edges, and geometry;
4. delete unrelated background/scene pixels;
5. keep every legitimate product component;
6. use the clean-canvas procedure when the page background cannot be removed.

Do not accept the result just because Canva reports success.

## 5. Background Remover procedure

Use Background Remover when Magic Grab is unavailable or poorer quality:

1. select the exact product image;
2. run BG Remover;
3. inspect the entire product at useful zoom;
4. restore/retry if product pixels, label, logo, cap, or edge were removed;
5. continue only when identity and geometry are visually correct.

## 6. Magic Layers procedure

For promotional or multi-object source images:

1. invoke Magic Layers/image-to-design;
2. identify all legitimate product elements;
3. remove text, CTA, decorations, unrelated food/props, and background fragments;
4. never delete a legitimate product component;
5. inspect the result before export.

MCP has no direct proven Magic Grab tool. The fixed-page/root background may be non-deletable through MCP. Use the actual Canva UI or move the isolated elements to a clean canvas.

## 7. Fixed-page background workaround

If the Magic Layers root background cannot be deleted:

1. create a clean Canva design;
2. set its width and height to the standard `1000x1000` px canvas;
3. transfer only the isolated product element(s);
4. preserve the original scale and aspect ratio;
5. do not crop, stretch, or add a white replacement background.

## 8. Standard canvas rule

Every product uses the same working canvas. Create the clean Canva page and
export the transparent cutout at exactly `1000x1000` px:

```text
clean page:  1000x1000
export:      1000x1000 PNG with alpha
```

The original product source may be a different native size; BOSMAX standardizes
the trusted source internally. If the Canva export is cropped or resized, do
not upload it. Correct the Canva design first.

## 9. Transparent PNG export

Export `PNG` and enable `Transparent Background`. Canva’s visible checkerboard/white appearance is not proof of alpha. MCP has no proven PNG export path; use a real operator download from Canva.

Upload the file using `Upload Canva PNG → Manual Review`. BOSMAX independently verifies:

- PNG format;
- exact `1000x1000` canvas dimensions;
- alpha-bearing mode/metadata;
- transparent pixels;
- visible product pixels.

RGB white-background PNGs are rejected with `CANVA_ALPHA_REQUIRED`.

## 10. Manual-lane handoff and approval

After successful verification:

1. BOSMAX registers the PNG through the existing PR #683 manual cutout lane.
2. The active candidate becomes `PENDING_REVIEW`.
3. Inspect the comparison panel and source lineage.
4. Enter reviewer identity and note.
5. confirm Identity, Label/logo, and Geometry/scale;
6. click `Approve Exact Cutout` only when the active candidate is correct.

Canva provenance is retained as `CANVA_MAGIC_GRAB`, `CANVA_BG_REMOVER`, or `CANVA_MAGIC_LAYERS` inside Product Truth provenance. The underlying history source kind remains `USER_UPLOAD` for compatibility with the manual override authority.

If quality is poor, click `Reject Cutout` and use `Use Original Fallback`. The fallback is the same-product trusted source; it is not a substitute for an approved exact cutout, so Exact Commerce may remain `CUTOUT_REQUIRED`.

## 11. Bulk queue procedure

1. Click `Prepare Canva Cutouts`.
2. Inspect eligible, approved, pending, Pro-blocked, missing-source, blocked, and remaining counts.
3. Select the observed transparent export entitlement.
4. Confirm only the bounded cohort you intend to operate; default is three.
5. If preflight is unknown, the durable run is `PAUSED`; complete preflight before `Resume`.
6. If transparent export is Pro-gated, the durable run is `BLOCKED_CANVA_PRO_REQUIRED`; do not work around it with a white RGB export.
7. Use `Pause` before stepping away. Use `Resume` only after confirming the live Canva capabilities again.
8. Use `Cancel` to terminate the remaining queue. Completed/pending-review candidates remain preserved.
9. Use the per-product `Canva Cutout` action for a bypass or priority item. It remains independent of this queue.

The queue is durable in `canva_cutout_bulk_run` and `canva_cutout_bulk_item`; a browser restart or backend restart does not erase the run cursor. It is an operator queue, not an unproven bulk Canva automation worker.

## 12. Retry policy

- Retry only after recording the failure reason.
- Re-run preflight if the Canva session, workspace, entitlement, or source bytes changed.
- A source SHA change requires a new preflight and a new workflow attempt.
- Do not retry a Pro-blocked transparent export with the same account.
- Do not retry hundreds of products after one UI failure; prove the next attempt on the bounded representative cohort.
- Never auto-approve a retry.

## 13. Common errors and exact recovery

| Error/evidence | Recovery |
| --- | --- |
| `CANVA_PRO_REQUIRED` / transparent export crown | Stop. Obtain the required entitlement or choose a different approved workflow; do not start editing or export RGB. |
| `CANVA_LOGIN_REQUIRED` | Log in to the intended Canva workspace and record preflight again. |
| `CANVA_METHOD_UNAVAILABLE` | Pick a method observed as available: Magic Grab, BG Remover, or Magic Layers. |
| `CANVA_CANVAS_DIMENSIONS_MISMATCH` | Rebuild the design on the standard `1000x1000` canvas and export again. |
| `CANVA_ALPHA_REQUIRED` | Export a real transparent PNG. A white RGB PNG is rejected. |
| MCP cannot delete root/fixed-page background | Use actual Canva UI or clean same-size canvas; preserve product elements. |
| MCP has no direct Magic Grab tool | Perform Magic Grab in Canva UI; record only observed evidence. |
| MCP has no proven PNG export | Download through the real Canva UI, then upload to BOSMAX. |
| product is archived/purged/test | Do not bypass the gate; use an active canonical product row. |
| candidate quality is poor | Reject, preserve history, select same-product fallback, and leave Exact Commerce fail-closed. |

## 14. Bounded UAT acceptance

Run at most three representative products: isolated packaging, complex promotional image, and difficult/irregular edge. Each must show source/output dimensions, alpha verification, manual-lane receipt, pending review, and preserved fallback. A Canva Pro entitlement block means the honest verdict is `PASS_WITH_CANVA_PRO_REQUIRED`, not factory-ready. The current local bounded receipt stops before editing for all three representatives when transparent export is `PRO_REQUIRED`; it does not claim PNG, alpha, or approval evidence.
