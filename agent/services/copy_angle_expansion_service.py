"""Expand a product's angle set from the Copy Components panel.

Angles are derived one-per-pain from the approved product-intelligence snapshot's
buyer persona. To add angles we append pains to that persona and re-approve a new
snapshot version — preserving ALL existing product truth verbatim. This is the
server-side engine behind the panel's "Tambah angle" control (free — no AI).

Fail-closed: a CLAIM_BLOCKED result is NOT approved (banned tokens in the pain
text); the caller is told so. Everything else is approved with the owner's panel
action standing as the claim-review acknowledgement, and the product-knowledge
gate relaxed (angles do not need product-truth completeness). Capped at
MAX_ANGLES.
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
    """Append `new_pains` (angles) to the product's persona and re-approve.

    Returns {ok, angle_count, added, capped, claim_gate, snapshot_version} on
    success; {ok: False, error, ...} when the additions are CLAIM_BLOCKED.
    Raises ValueError for NO_PAINS_PROVIDED / NO_APPROVED_SNAPSHOT / ANGLES_FULL.
    """
    from agent.db import crud
    from agent.models.product_intelligence_review_draft import (
        ProductIntelligenceReviewDraftApproveRequest,
        ProductIntelligenceReviewDraftCreateRequest,
    )
    from agent.services import product_intelligence_review_draft_service as draft_svc

    pains_in = [p.strip() for p in (new_pains or []) if p and p.strip()]
    if not pains_in:
        raise ValueError("NO_PAINS_PROVIDED")

    snap = await crud.get_latest_approved_product_intelligence_snapshot(product_id)
    if not snap:
        raise ValueError("NO_APPROVED_SNAPSHOT")

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

    fields: dict[str, Any] = {
        "buyer_persona_snapshot_json": persona,
        "reviewer_note": f"Angle expansion via Copy Components panel: +{len(added)} use-case(s).",
        "created_by": "copy_components_panel_add_angle",
    }
    for f in _JSON_FIELDS:
        fields[f] = _parse(snap.get(f), None)
    for f in _TEXT_FIELDS:
        fields[f] = snap.get(f)
    request = ProductIntelligenceReviewDraftCreateRequest(
        **{k: v for k, v in fields.items() if v is not None}
    )
    draft = await draft_svc.create_review_draft(product_id, request)

    if draft.claim_gate == "CLAIM_BLOCKED":
        return {
            "ok": False,
            "error": "CLAIM_BLOCKED",
            "claim_tokens": list(draft.claim_tokens_json or []),
            "angle_count": len(existing),
            "added": 0,
        }

    snapshot = await draft_svc.approve_review_draft(
        draft.draft_id,
        ProductIntelligenceReviewDraftApproveRequest(
            approved_by="operator",
            approval_note="Angle expansion via Copy Components panel.",
            allow_incomplete_product_knowledge=True,
            claim_review_acknowledged=True,
        ),
    )
    angles = derive_angles(persona).get("angles") or []
    return {
        "ok": True,
        "angle_count": len(angles),
        "added": len(added),
        "capped": capped,
        "claim_gate": draft.claim_gate,
        "snapshot_version": snapshot.version,
    }
