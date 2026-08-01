"""One idempotent door: every runtime intake ends with a Product Intelligence draft.

WHY NOT A create_product_with_intelligence() WRAPPER
A create-only wrapper looked sufficient until the FastMoss importer was read closely.
`agent/api/products.py:1102-1106` is an UPSERT:

    existing = await _find_product_by_exact_title(raw_title)
    if existing:
        updated_product = await crud.update_product(existing["id"], **payload)
        ...
        continue                      # <- never reaches create_product
    created = await crud.create_product(**payload)

So the highest-volume lane (up to 500 rows per call) re-imports straight past any
create-time hook. The invariant therefore has to be an ENSURE over the product's current
state, called after create AND after update/re-import AND on recompute.

THE IDEMPOTENCY PROBLEM THIS SOLVES
"Does a draft exist?" is not a strong enough test. Re-importing the same 500 FastMoss rows
must not manufacture 500 fresh review items when nothing changed. Conversely, genuinely
changed evidence must not be swallowed. The decision is therefore made on a stable
NORMALIZED EVIDENCE DIGEST:

    approved snapshot, same evidence   -> NOOP_APPROVED_SNAPSHOT   (never downgraded)
    open draft, same evidence          -> NOOP_DRAFT_UP_TO_DATE    (reused, not duplicated)
    open draft, changed evidence       -> UPDATED_REVIEW_REQUIRED
    no draft                           -> CREATED (minimal when nothing is promotable)

The digest is computed from the SAME normalized field set on both sides — the incoming
promotion payload and the stored draft row — so no new column is needed and a re-import
that changes nothing is provably a no-op.

WHAT THIS NEVER DOES
  * never approves: no approved_by / approved_at / acknowledgement is written here;
  * never overwrites or downgrades an APPROVED snapshot or a terminal draft;
  * never calls a paid provider. `prepare_product_for_copywriting` spends tokens and stays
    operator-initiated; wiring it here would fire it 500x per FastMoss import.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from agent.services.registration_intelligence_promotion_service import (
    PROMOTION_MAP,
    build_create_request,
    build_promotion_payload,
    build_provenance_inputs,
)

# Outcomes. Returned verbatim so a caller (and a test) can assert WHICH branch ran.
NOOP_APPROVED_SNAPSHOT = "NOOP_APPROVED_SNAPSHOT"
NOOP_DRAFT_UP_TO_DATE = "NOOP_DRAFT_UP_TO_DATE"
UPDATED_REVIEW_REQUIRED = "UPDATED_REVIEW_REQUIRED"
CREATED = "CREATED"
CREATED_MINIMAL = "CREATED_MINIMAL"
SKIPPED_TERMINAL_DRAFT = "SKIPPED_TERMINAL_DRAFT"

_TERMINAL = {"APPROVED", "REJECTED"}
_DIGEST_TARGETS = tuple(target for target, _sources in PROMOTION_MAP)
_LIST_TARGETS = {"benefits_json", "usp_json"}


def _norm(target: str, value: Any) -> Any:
    """Normalize one field so a stored row and an in-memory payload compare equal.

    Stored list columns arrive as JSON text; payload holds real lists. Whitespace-only is
    indistinguishable from absent for digest purposes.
    """
    if value is None:
        return None
    if target in _LIST_TARGETS:
        items = value
        if isinstance(items, (str, bytes)):
            try:
                items = json.loads(items)
            except (ValueError, TypeError):
                items = [items]
        if not isinstance(items, (list, tuple)):
            items = [items]
        cleaned = [str(v).strip() for v in items if str(v).strip()]
        return cleaned or None
    text = str(value).strip()
    return text or None


def evidence_digest(fields: Mapping[str, Any]) -> str:
    """Stable digest over the promotable evidence only.

    Deliberately excludes updated_at, review_status, claim scores and anything else the
    system recomputes — otherwise every recompute would look like changed evidence and the
    no-op branch could never fire.
    """
    material = {t: _norm(t, fields.get(t)) for t in _DIGEST_TARGETS}
    material = {k: v for k, v in material.items() if v is not None}
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def digest_of_payload(payload: Mapping[str, Any]) -> str:
    return evidence_digest(payload.get("fields") or {})


def digest_of_stored_draft(row: Mapping[str, Any]) -> str:
    return evidence_digest(row)


class IntakeEvidence:
    """Duck-typed stand-in for a RegistrationReviewDraft.

    The four bypassing lanes in `agent/api/products.py` have no registration draft — they
    hold a raw payload dict. Rather than fork the promotion logic for them, adapt the
    payload into the same shape `build_promotion_payload` already reads, so all lanes share
    one mapping table and one set of drop reasons.

    Everything supplied here counts as DECLARED evidence: it came from an operator action
    or an imported source row, not from an unreviewed AI proposal.
    """

    __slots__ = ("declared_evidence_fields", "canonical_candidate_fields",
                 "approval_checklist", "claim_risk_level", "claim_tokens", "source_lane")

    def __init__(self, fields: Mapping[str, Any], *, lane: str,
                 claim_risk_level: str | None = None):
        self.declared_evidence_fields = {k: v for k, v in dict(fields).items()
                                         if v is not None}
        self.canonical_candidate_fields = {}
        self.approval_checklist = {}
        self.claim_risk_level = claim_risk_level or "MEDIUM"
        self.claim_tokens = []
        self.source_lane = lane


def evidence_from_product_payload(payload: Mapping[str, Any], *, lane: str) -> IntakeEvidence:
    """Adapt a product-create/update payload into intake evidence.

    Only keys that PROMOTION_MAP already understands are forwarded; identity, taxonomy,
    physics and commerce columns are deliberately NOT knowledge evidence.
    """
    known: set[str] = {src for _t, sources in PROMOTION_MAP for src in sources}
    known |= {"source_url", "product_url", "tiktok_product_url", "tiktok_shop_url",
              "image_url", "local_image_path"}
    return IntakeEvidence(
        {k: v for k, v in dict(payload).items() if k in known},
        lane=lane,
        claim_risk_level=str(payload.get("claim_risk_level") or "") or None,
    )


async def _latest_open_draft(product_id: str):
    """Newest non-terminal draft, or (None, terminal_seen)."""
    from agent.db.schema import get_db

    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM product_intelligence_review_draft WHERE product_id=? "
        "ORDER BY COALESCE(updated_at, created_at) DESC, draft_id DESC",
        (product_id,),
    )
    rows = [dict(r) for r in await cur.fetchall()]
    await cur.close()
    terminal_seen = any(str(r.get("review_status") or "").upper() in _TERMINAL
                        for r in rows)
    for row in rows:
        if str(row.get("review_status") or "").upper() not in _TERMINAL:
            return row, terminal_seen
    return None, terminal_seen


async def _has_approved_snapshot(product_id: str) -> bool:
    from agent.db.schema import get_db

    db = await get_db()
    cur = await db.execute(
        "SELECT 1 FROM product_intelligence_snapshot WHERE product_id=? LIMIT 1",
        (product_id,),
    )
    row = await cur.fetchone()
    await cur.close()
    return row is not None


async def _write_provenance(draft_id: str, product_id: str, draft, payload) -> int:
    from agent.db import crud

    written = 0
    for row in build_provenance_inputs(draft, payload):
        await crud.create_product_intelligence_review_field_provenance(
            draft_id=draft_id,
            product_id=product_id,
            field_name=row.field_name,
            source_type=row.source_type,
            evidence_kind=row.evidence_kind,
            extraction_method=row.extraction_method,
            verification_status=row.verification_status,
            declared_value=row.declared_value,
            normalized_value=row.normalized_value,
            source_url=row.source_url,
            source_lane=row.source_lane,
            confidence_score=row.confidence_score,
            claim_risk_flag=row.claim_risk_flag,
            reviewer_decision=row.reviewer_decision,
            reviewer_note=row.reviewer_note,
        )
        written += 1
    return written


async def ensure_product_intelligence(
    product_id: str,
    draft: Any,
    *,
    lane: str,
) -> dict[str, Any]:
    """Idempotently guarantee this product has an up-to-date intelligence draft.

    Safe to call after create, after update / re-import, and on recompute. Calling it
    twice with unchanged evidence is a no-op, so a replayed request or a 500-row FastMoss
    re-import cannot manufacture duplicate review debt.
    """
    from agent.models.product_intelligence_review_draft import (
        ProductIntelligenceReviewDraftUpdateRequest,
    )
    from agent.services import product_intelligence_review_draft_service as svc

    payload = build_promotion_payload(draft)
    incoming = digest_of_payload(payload)
    minimal = not payload["fields"]

    # An approved snapshot is human-ratified Product Truth. Re-importing the same evidence
    # must never disturb it, and this seam never downgrades one.
    if await _has_approved_snapshot(product_id) and not minimal:
        existing_open, _terminal = await _latest_open_draft(product_id)
        if existing_open is None or digest_of_stored_draft(existing_open) == incoming:
            return {"outcome": NOOP_APPROVED_SNAPSHOT, "lane": lane,
                    "product_id": product_id, "evidence_digest": incoming,
                    "intelligence_draft_id": (existing_open or {}).get("draft_id"),
                    "wrote": False}

    open_draft, terminal_seen = await _latest_open_draft(product_id)

    if open_draft is not None:
        if digest_of_stored_draft(open_draft) == incoming:
            return {"outcome": NOOP_DRAFT_UP_TO_DATE, "lane": lane,
                    "product_id": product_id, "evidence_digest": incoming,
                    "intelligence_draft_id": open_draft["draft_id"], "wrote": False}
        if minimal:
            # Nothing new to say; do not blank an existing draft.
            return {"outcome": NOOP_DRAFT_UP_TO_DATE, "lane": lane,
                    "product_id": product_id, "evidence_digest": incoming,
                    "intelligence_draft_id": open_draft["draft_id"], "wrote": False,
                    "reason": "NO_PROMOTABLE_FIELDS"}
        updated = await svc.update_review_draft(
            str(open_draft["draft_id"]),
            ProductIntelligenceReviewDraftUpdateRequest(
                **build_create_request(payload).model_dump(exclude_unset=True)),
        )
        draft_id = getattr(updated, "draft_id", open_draft["draft_id"])
        return {"outcome": UPDATED_REVIEW_REQUIRED, "lane": lane,
                "product_id": product_id, "evidence_digest": incoming,
                "intelligence_draft_id": draft_id,
                "review_status": getattr(updated, "review_status", None),
                "provenance_rows": await _write_provenance(
                    str(draft_id), product_id, draft, payload),
                "promoted_fields": [p["target"] for p in payload["promoted_fields"]],
                "dropped_fields": payload["dropped_fields"], "wrote": True}

    if terminal_seen and minimal:
        # Every draft is terminal and there is nothing new — leave the decision alone.
        return {"outcome": SKIPPED_TERMINAL_DRAFT, "lane": lane,
                "product_id": product_id, "evidence_digest": incoming,
                "intelligence_draft_id": None, "wrote": False}

    created = await svc.create_review_draft(product_id, build_create_request(payload))
    draft_id = getattr(created, "draft_id", None)
    return {
        "outcome": CREATED_MINIMAL if minimal else CREATED,
        "lane": lane,
        "product_id": product_id,
        "evidence_digest": incoming,
        "intelligence_draft_id": draft_id,
        "review_status": getattr(created, "review_status", None),
        "minimal_draft": minimal,
        "reason": "NO_PROMOTABLE_FIELDS" if minimal else None,
        "promoted_fields": [p["target"] for p in payload["promoted_fields"]],
        "dropped_fields": payload["dropped_fields"],
        "provenance_rows": await _write_provenance(
            str(draft_id), product_id, draft, payload) if draft_id else 0,
        "wrote": True,
    }
