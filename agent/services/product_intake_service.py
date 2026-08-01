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


# Material evidence: WHERE a value came from. Deliberately separate from the value digest
# (B-586-02) — the same text backed by a newly acquired marketplace page or OCR is NOT a
# no-op. Swallowing it would defeat the point of an evidence-closure mission.
_EVIDENCE_KEYS = ("source_urls_json", "image_evidence_json")


def _material_map(payload_or_row: Mapping[str, Any]) -> dict[str, str]:
    """Flatten every asserted source/image reference to a comparable value set."""
    out: dict[str, str] = {}
    for key in _EVIDENCE_KEYS:
        raw = payload_or_row.get(key)
        if isinstance(raw, (str, bytes)):
            try:
                raw = json.loads(raw)
            except (ValueError, TypeError):
                raw = None
        if isinstance(raw, Mapping):
            for k, v in raw.items():
                text = str(v or "").strip()
                if not text or text.lower() in ("true", "false"):
                    continue  # flags/ids the service injects are not evidence refs
                if "://" in text or k == "local_image_path":
                    out[f"{key}.{k}"] = text
    return out


def material_evidence_digest(
    payload_or_row: Mapping[str, Any], *, lane: str | None = None,
) -> str:
    material: dict[str, Any] = dict(_material_map(payload_or_row))
    if lane:
        material["lane"] = lane
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")
    ).hexdigest()


# Verification strength. Evidence that has been upgraded from imported/unverified to
# acquired/verified is NEW information even when the text is byte-identical, so it must
# not be swallowed as a no-op (B-586-02).
_VERIFICATION_RANK = {
    "": 0, "NONE": 0,
    "PENDING_REVIEW": 1,
    "REVIEWED": 2,
    "OPERATOR_CONFIRMED": 3,
    "VERIFIED": 4,
}


def verification_rank(status: Any) -> int:
    return _VERIFICATION_RANK.get(str(status or "").strip().upper(), 1)


def evidence_signature(row: Mapping[str, Any]) -> tuple[str, str, str]:
    """Identity of ONE piece of material evidence, ignoring its verification strength."""
    return (
        str(row.get("source_url") or "").strip(),
        str(row.get("source_type") or "").strip().upper(),
        str(row.get("extraction_method") or "").strip().upper(),
    )


def provenance_is_covered(
    stored_rows, incoming_rows,
) -> bool:
    """True only when every incoming evidence claim is ALREADY recorded at >= strength.

    Comparing source URLs alone (the previous behaviour) meant the same URL re-acquired
    through a stronger lane — imported/PENDING_REVIEW upgraded to acquired/VERIFIED — was
    reported as a no-op and the upgrade was never persisted.
    """
    best: dict[tuple[str, str, str], int] = {}
    for row in stored_rows or ():
        sig = evidence_signature(row)
        rank = verification_rank(row.get("verification_status"))
        best[sig] = max(best.get(sig, -1), rank)
    for row in incoming_rows or ():
        sig = evidence_signature(row)
        if best.get(sig, -1) < verification_rank(row.get("verification_status")):
            return False
    return True


def material_is_covered(stored: Mapping[str, Any], incoming: Mapping[str, Any]) -> bool:
    """Does the stored row already carry every source/image the incoming payload asserts?

    Equality is the WRONG test here: `create_review_draft` enriches `source_urls_json`
    itself (it injects source_type / product_id / product_name), so a raw stored-vs-incoming
    comparison never matches and every re-import would look like changed evidence.
    Coverage is the right question — "is this source already recorded?" — and it still
    satisfies B-586-02, because a genuinely NEW or stronger source is not covered.
    """
    stored_values = set(_material_map(stored).values())
    return all(v in stored_values for v in _material_map(incoming).values())


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

    B-586-07: these lanes are NOT all operator-declared. A FastMoss workbook row and a
    TikTok import are IMPORTED marketplace evidence; labelling them OPERATOR_DECLARED /
    REGISTRATION_COMMIT asserts a human vouched for them when nobody did. Each lane
    therefore declares its own source_type and evidence_kind.
    """

    __slots__ = ("declared_evidence_fields", "canonical_candidate_fields",
                 "approval_checklist", "claim_risk_level", "claim_tokens", "source_lane",
                 "provenance_source_type", "provenance_evidence_kind",
                 "provenance_extraction_method")

    def __init__(self, fields: Mapping[str, Any], *, lane: str,
                 claim_risk_level: str | None = None,
                 source_type: str | None = None,
                 evidence_kind: str | None = None,
                 extraction_method: str | None = None):
        self.provenance_source_type = source_type or "REGISTRATION_COMMIT"
        self.provenance_evidence_kind = evidence_kind or "OPERATOR_DECLARED"
        self.provenance_extraction_method = extraction_method or "REGISTRATION_PROMOTION"
        self.declared_evidence_fields = {k: v for k, v in dict(fields).items()
                                         if v is not None}
        self.canonical_candidate_fields = {}
        self.approval_checklist = {}
        self.claim_risk_level = claim_risk_level or "MEDIUM"
        self.claim_tokens = []
        self.source_lane = lane


# What each intake lane may truthfully claim about its own evidence.
LANE_PROVENANCE: dict[str, dict[str, str]] = {
    # a human typed it into the product form
    "PRODUCTS_MANUAL": {"source_type": "OPERATOR_MANUAL_ENTRY",
                        "evidence_kind": "OPERATOR_DECLARED",
                        "extraction_method": "MANUAL_PRODUCT_FORM"},
    "PRODUCTS_MAP_PERSIST": {"source_type": "OPERATOR_MANUAL_ENTRY",
                             "evidence_kind": "OPERATOR_DECLARED",
                             "extraction_method": "MAPPING_PERSIST"},
    "PRODUCTS_PHYSICS_MAP_PERSIST": {"source_type": "DERIVED_PHYSICS",
                                     "evidence_kind": "SYSTEM_DERIVED",
                                     "extraction_method": "PHYSICS_MAP"},
    # imported marketplace rows: nobody vouched for these
    "PRODUCTS_FASTMOSS_IMPORT": {"source_type": "IMPORTED_FASTMOSS",
                                 "evidence_kind": "IMPORTED_MARKETPLACE_ROW",
                                 "extraction_method": "FASTMOSS_WORKBOOK"},
    "PRODUCTS_FASTMOSS_REIMPORT": {"source_type": "IMPORTED_FASTMOSS",
                                   "evidence_kind": "IMPORTED_MARKETPLACE_ROW",
                                   "extraction_method": "FASTMOSS_WORKBOOK"},
    "PRODUCTS_TIKTOKSHOP_IMPORT": {"source_type": "IMPORTED_TIKTOKSHOP",
                                   "evidence_kind": "IMPORTED_MARKETPLACE_LINK",
                                   "extraction_method": "TIKTOKSHOP_LINK"},
    "_DEFAULT": {"source_type": "REGISTRATION_COMMIT",
                 "evidence_kind": "OPERATOR_DECLARED",
                 "extraction_method": "REGISTRATION_PROMOTION"},
}


def evidence_from_product_payload(payload: Mapping[str, Any], *, lane: str) -> IntakeEvidence:
    """Adapt a product-create/update payload into intake evidence.

    Only keys that PROMOTION_MAP already understands are forwarded; identity, taxonomy,
    physics and commerce columns are deliberately NOT knowledge evidence.
    """
    known: set[str] = {src for _t, sources in PROMOTION_MAP for src in sources}
    known |= {"source_url", "product_url", "tiktok_product_url", "tiktok_shop_url",
              "image_url", "local_image_path"}
    semantics = LANE_PROVENANCE.get(lane, LANE_PROVENANCE["_DEFAULT"])
    return IntakeEvidence(
        {k: v for k, v in dict(payload).items() if k in known},
        lane=lane,
        claim_risk_level=str(payload.get("claim_risk_level") or "") or None,
        **semantics,
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


async def _approved_snapshot(product_id: str) -> dict | None:
    """The APPROVED snapshot only.

    B-586-01: the first version selected ANY snapshot row. `SUPERSEDED` is a real stored
    status (9 rows live today) and `DRAFT` / `REJECTED` / `ARCHIVED` are permitted by the
    schema, so a superseded snapshot was being treated as ratified Product Truth.
    """
    from agent.db.schema import get_db

    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM product_intelligence_snapshot WHERE product_id=? "
        "AND UPPER(COALESCE(status,'')) = 'APPROVED' "
        "ORDER BY COALESCE(version, 0) DESC, COALESCE(updated_at, created_at) DESC LIMIT 1",
        (product_id,),
    )
    row = await cur.fetchone()
    await cur.close()
    return dict(row) if row else None


async def _stored_provenance(draft_id: str) -> list[dict]:
    from agent.db.schema import get_db

    db = await get_db()
    cur = await db.execute(
        "SELECT source_url, source_type, extraction_method, verification_status "
        "FROM product_intelligence_review_field_provenance WHERE draft_id=?", (draft_id,))
    rows = [dict(r) for r in await cur.fetchall()]
    await cur.close()
    return rows


async def _incoming_covered(draft_row: Mapping[str, Any], draft: Any,
                            payload: Mapping[str, Any]) -> bool:
    """Production wiring for B-586-02.

    `material_is_covered` compares source URL / image values only. Verification strength,
    source type and extraction method live in the provenance table, so an upgrade from
    imported+PENDING_REVIEW to acquired+VERIFIED on the SAME url looked identical to it.
    Both checks must pass for a no-op.
    """
    if not material_is_covered(draft_row, payload):
        return False
    stored = await _stored_provenance(str(draft_row.get("draft_id") or ""))
    incoming = [
        {"source_url": r.source_url, "source_type": r.source_type,
         "extraction_method": r.extraction_method,
         "verification_status": r.verification_status}
        for r in build_provenance_inputs(draft, payload)
    ]
    return provenance_is_covered(stored, incoming)


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
    payload_material = {"source_urls_json": payload.get("source_urls_json"),
                        "image_evidence_json": payload.get("image_evidence_json")}
    # the full payload is needed for provenance comparison, not just the material keys
    payload_material_row = payload
    incoming_material = material_evidence_digest(payload_material, lane=None)
    # A source-only / image-only re-import carries no knowledge field but DOES carry new
    # material evidence, so it must not be treated as "nothing to do".
    minimal = not payload["fields"]

    # B-586-01. An APPROVED snapshot is human-ratified Product Truth, so it is never
    # modified or downgraded here — but "an approved snapshot exists" must NOT mean
    # "discard whatever arrived next". The first version returned NOOP whenever there was
    # no open draft, regardless of the incoming values, so evidence that changed AFTER
    # approval was silently thrown away. Compare against the snapshot itself instead.
    approved = await _approved_snapshot(product_id)
    if approved is not None and not minimal:
        snapshot_values = digest_of_stored_draft(approved)
        approved_covered = material_is_covered(approved, payload_material)
        if snapshot_values == incoming and approved_covered:
            open_same, _t = await _latest_open_draft(product_id)
            return {"outcome": NOOP_APPROVED_SNAPSHOT, "lane": lane,
                    "product_id": product_id, "evidence_digest": incoming,
                    "material_digest": incoming_material,
                    "approved_snapshot_id": approved.get("snapshot_id"),
                    "intelligence_draft_id": (open_same or {}).get("draft_id"),
                    "wrote": False}
        # values or sources moved on since approval -> that is a new review item, not a
        # no-op and not an edit of the ratified snapshot.

    open_draft, terminal_seen = await _latest_open_draft(product_id)

    if open_draft is not None:
        same_values = digest_of_stored_draft(open_draft) == incoming
        same_material = await _incoming_covered(open_draft, draft, payload_material_row)
        # B-586-02: identical text backed by a NEW or stronger source is not a no-op.
        if same_values and same_material:
            return {"outcome": NOOP_DRAFT_UP_TO_DATE, "lane": lane,
                    "product_id": product_id, "evidence_digest": incoming,
                    "material_digest": incoming_material,
                    "intelligence_draft_id": open_draft["draft_id"], "wrote": False}
        if minimal and same_material:
            # Nothing new to say; do not blank an existing draft.
            return {"outcome": NOOP_DRAFT_UP_TO_DATE, "lane": lane,
                    "product_id": product_id, "evidence_digest": incoming,
                    "material_digest": incoming_material,
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
