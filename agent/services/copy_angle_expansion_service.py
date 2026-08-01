"""Expand a product's angle set from the Copy Components panel.

Angles are derived one-per-pain from the approved product-intelligence snapshot's
buyer persona. Adding angles appends pains to that persona in a REVIEW-REQUIRED
draft — preserving ALL existing product truth verbatim. This is the server-side
engine behind the panel's "Tambah angle" control (free — no AI).

Mission-08D: this lane previously re-APPROVED the draft automatically (panel click
standing in for the reviewer). That was the last path able to mint an approved
Product Intelligence snapshot without an explicit reviewer approval action, and it
is exactly how 318 historical snapshots froze MISSING_REQUIRED_FIELDS while
reporting as complete. It now stops at the draft: the persona expansion is staged,
the response says review-required, and the snapshot only ever comes from the
governed Approve action in the Product Intelligence panel.

Fail-closed: a CLAIM_BLOCKED result is reported as such (banned tokens in the pain
text). Idempotent: a retry updates the SAME open draft instead of minting
duplicates. Capped at MAX_ANGLES.
"""
from __future__ import annotations

import json
from typing import Any

from agent.services.copy_angle_derivation import MAX_ANGLES, derive_angles

# Snapshot fields carried forward verbatim so no product truth is lost.
_JSON_FIELDS = (
    "copy_strategy_summary_json",
    "benefits_json",
    "usp_json",
    "allowed_claims_json",
    "source_urls_json",
    "image_evidence_json",
)
_TEXT_FIELDS = (
    "product_description",
    "usage_text",
    "ingredients_text",
    "warnings_text",
    "target_customer_text",
    "size_or_volume",
    "product_form_factor",
    "packaging_description",
    "package_notes",
    "product_truth_lock",
)


def _parse(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:  # noqa: BLE001
        return default


async def expand_product_angles(
    product_id: str,
    new_pains: list[str],
) -> dict[str, Any]:
    """Append `new_pains` (angles) to the product's persona and stage review.

    Returns {ok, draft_id, review_required, angle_count, added, capped, claim_gate}
    on success; {ok: False, error, ...} when the additions are CLAIM_BLOCKED.
    Raises ValueError for NO_PAINS_PROVIDED / NO_APPROVED_SNAPSHOT / ANGLES_FULL.
    """
    from agent.db import crud
    from agent.models.product_intelligence_review_draft import (
        ProductIntelligenceReviewDraftCreateRequest,
        ProductIntelligenceReviewDraftUpdateRequest,
    )
    from agent.services import product_intelligence_review_draft_service as draft_svc

    pains_in = [p.strip() for p in (new_pains or []) if p and p.strip()]
    if not pains_in:
        raise ValueError("NO_PAINS_PROVIDED")

    snap = await crud.get_latest_approved_product_intelligence_snapshot(product_id)
    if not snap:
        raise ValueError("NO_APPROVED_SNAPSHOT")

    # The OPEN draft (if any) is the staging area: a second expansion before the first
    # is approved must build on the STAGED pains, or the earlier additions silently
    # vanish from the merge. The snapshot persona is only the base when nothing is
    # staged yet.
    open_draft = next(
        (item for item in (await draft_svc.list_review_drafts(product_id, limit=20)).items
         if item.review_status not in draft_svc.TERMINAL_STATUSES),
        None,
    )
    if open_draft is not None and (open_draft.buyer_persona_snapshot_json or {}).get("pains"):
        persona = dict(open_draft.buyer_persona_snapshot_json or {})
    else:
        persona = _parse(snap.get("buyer_persona_snapshot_json"), {}) or {}
    existing = [p for p in (persona.get("pains") or []) if isinstance(p, str)]
    if len(existing) >= MAX_ANGLES:
        raise ValueError(f"ANGLES_FULL:{MAX_ANGLES}")

    seen = {p.strip().lower() for p in existing}
    added = [p for p in pains_in if p.lower() not in seen]
    merged = existing + added
    capped = False
    if len(merged) > MAX_ANGLES:
        merged = merged[:MAX_ANGLES]
        added = merged[len(existing):]
        capped = True
    persona = {**persona, "pains": merged}

    expansion_note = f"Angle expansion via Copy Components panel: +{len(added)} use-case(s)."
    fields: dict[str, Any] = {
        "buyer_persona_snapshot_json": persona,
        "reviewer_note": "\n".join(
            part for part in (
                str(open_draft.reviewer_note or "").strip() if open_draft else "",
                expansion_note,
            )
            if part
        ),
        "created_by": (
            open_draft.created_by
            if open_draft is not None and open_draft.created_by
            else "copy_components_panel_add_angle"
        ),
    }
    for f in _JSON_FIELDS:
        fields[f] = (
            getattr(open_draft, f)
            if open_draft is not None
            else _parse(snap.get(f), None)
        )
    for f in _TEXT_FIELDS:
        fields[f] = (
            getattr(open_draft, f)
            if open_draft is not None
            else snap.get(f)
        )
    # Idempotent by construction: without the old auto-approve, the staged draft stays
    # OPEN, so a retry must UPDATE it rather than trip the one-open-draft rule
    # (B-586-04) minting an error or a duplicate.
    if open_draft is not None:
        draft = await draft_svc.update_review_draft(
            open_draft.draft_id,
            ProductIntelligenceReviewDraftUpdateRequest(
                **{k: v for k, v in fields.items() if v is not None}
            ),
        )
    else:
        draft = await draft_svc.create_review_draft(
            product_id,
            ProductIntelligenceReviewDraftCreateRequest(
                **{k: v for k, v in fields.items() if v is not None}
            ),
        )

    if draft.claim_gate == "CLAIM_BLOCKED":
        return {
            "ok": False,
            "error": "CLAIM_BLOCKED",
            "claim_tokens": list(draft.claim_tokens_json or []),
            "angle_count": len(existing),
            "added": 0,
        }

    # NO automatic approval and NO snapshot here — the expanded persona is staged as a
    # review-required draft and the governed Product Intelligence workflow (human
    # Validate + Approve) is the only path to a new snapshot version.
    angles = derive_angles(persona).get("angles") or []
    return {
        "ok": True,
        "approved": False,
        "review_required": True,
        "draft_id": draft.draft_id,
        "review_status": draft.review_status,
        "angle_count": len(angles),
        "added": len(added),
        "capped": capped,
        "claim_gate": draft.claim_gate,
        "next_action": ("Angles staged on a review-required draft. Approve it in the "
                        "Product Intelligence panel to publish a new snapshot."),
    }
