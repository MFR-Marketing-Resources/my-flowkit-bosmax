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

from agent.services.product_intelligence_draft_lifecycle import (
    SQL_CANONICAL_ORDER,
    TERMINAL_REVIEW_STATUSES,
    is_terminal,
)
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

# B-586-04: the open/terminal predicate is now owned by ONE module and shared with the
# database constraint, so the reader, the deduplicator and the UNIQUE index cannot disagree.
_TERMINAL = TERMINAL_REVIEW_STATUSES
_DIGEST_TARGETS = tuple(target for target, _sources in PROMOTION_MAP)
_LIST_TARGETS = {
    "benefits_json",
    "usp_json",
    "hook_angles_json",
    "cta_angles_json",
    "pain_points_json",
}


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


def evidence_signature(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    """Identity of ONE piece of material evidence, ignoring its verification strength.

    field_name is part of the identity. Without it, a VERIFIED row for
    product_description would "cover" a PENDING_REVIEW warnings_text sourced from the same
    page — one field's verification silently vouching for another field's unverified text.
    """
    return (
        str(row.get("field_name") or "").strip(),
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
                 "provenance_extraction_method", "provenance_verification_status",
                 "provenance_field_overrides")

    def __init__(self, fields: Mapping[str, Any], *, lane: str,
                 claim_risk_level: str | None = None,
                 source_type: str | None = None,
                 evidence_kind: str | None = None,
                 extraction_method: str | None = None,
                 verification_status: str | None = None,
                 field_overrides: Mapping[str, Mapping[str, str]] | None = None):
        # Per-field evidence identity, when the lane actually knows it (e.g. TikTok
        # extraction knows `price` came from JSON-LD and `product_description` from a meta
        # tag). Without this the whole draft collapses to one lane-wide method label.
        self.provenance_field_overrides = dict(field_overrides or {})
        self.provenance_verification_status = verification_status or "PENDING_REVIEW"
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
    # Re-acquiring an EXISTING product's own stored listing. Same evidence class as the
    # import, but these lane-wide values are only a fallback: this lane supplies exact
    # per-field methods (JSONLD / META / LABELLED_SECTION) via field_overrides.
    "PRODUCTS_TIKTOKSHOP_RECOMPUTE": {"source_type": "IMPORTED_TIKTOKSHOP",
                                      "evidence_kind": "IMPORTED_MARKETPLACE_LINK",
                                      "extraction_method": "TIKTOKSHOP_RECOMPUTE"},
    "_DEFAULT": {"source_type": "REGISTRATION_COMMIT",
                 "evidence_kind": "OPERATOR_DECLARED",
                 "extraction_method": "REGISTRATION_PROMOTION"},
}


def evidence_from_product_payload(
    payload: Mapping[str, Any], *, lane: str,
    field_overrides: Mapping[str, Mapping[str, str]] | None = None,
) -> IntakeEvidence:
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
        field_overrides=field_overrides,
        **semantics,
    )


async def _latest_open_draft(product_id: str):
    """Newest non-terminal draft, or (None, terminal_seen)."""
    from agent.db.schema import get_db

    db = await get_db()
    cur = await db.execute(
        "SELECT * FROM product_intelligence_review_draft WHERE product_id=? "
        f"ORDER BY {SQL_CANONICAL_ORDER}",
        (product_id,),
    )
    rows = [dict(r) for r in await cur.fetchall()]
    await cur.close()
    terminal_seen = any(is_terminal(r.get("review_status")) for r in rows)
    for row in rows:
        if not is_terminal(row.get("review_status")):
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
        "SELECT field_name, source_url, source_type, extraction_method, "
        "verification_status FROM product_intelligence_review_field_provenance "
        "WHERE draft_id=?", (draft_id,))
    rows = [dict(r) for r in await cur.fetchall()]
    await cur.close()
    return rows


async def _approved_snapshot_provenance_covers(
    approved: Mapping[str, Any], draft: Any, payload: Mapping[str, Any],
) -> bool:
    """Coverage scoped to the APPROVED SNAPSHOT'S OWN lineage.

    Reading every provenance row the product ever had let evidence from a rejected,
    archived or superseded draft vouch for the current approved snapshot. The snapshot
    records `created_from_review_draft_id` (present on 445 of 447 live rows), which is the
    authoritative lineage — no timestamp guessing. A snapshot WITHOUT lineage cannot prove
    coverage, so it fails closed and the incoming evidence is captured.
    """
    from agent.db.schema import get_db

    origin = str(approved.get("created_from_review_draft_id") or "").strip()
    if not origin:
        return False
    db = await get_db()
    cur = await db.execute(
        "SELECT field_name, source_url, source_type, extraction_method, "
        "verification_status FROM product_intelligence_review_field_provenance "
        "WHERE draft_id=?", (origin,))
    stored = [dict(r) for r in await cur.fetchall()]
    await cur.close()
    incoming = [
        {"field_name": r.field_name, "source_url": r.source_url,
         "source_type": r.source_type, "extraction_method": r.extraction_method,
         "verification_status": r.verification_status}
        for r in build_provenance_inputs(draft, payload)
    ]
    return provenance_is_covered(stored, incoming)


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
        {"field_name": r.field_name, "source_url": r.source_url,
         "source_type": r.source_type, "extraction_method": r.extraction_method,
         "verification_status": r.verification_status}
        for r in build_provenance_inputs(draft, payload)
    ]
    return provenance_is_covered(stored, incoming)


async def _write_provenance(draft_id: str, product_id: str, draft, payload) -> int:
    """Write ALL provenance rows for a draft inside the caller's transaction.

    B-586-03: `crud.create_product_intelligence_review_field_provenance` commits per row,
    so a batch that failed midway left some rows behind. Every row now goes in under one
    `atomic()` boundary; when the caller has already opened one, this joins it, so the
    draft mutation and its provenance commit or roll back together.
    """
    from agent.db import crud
    from agent.db.schema import atomic

    rows = build_provenance_inputs(draft, payload)
    if not rows:
        return 0
    now = crud._now()
    async with atomic() as db:
        for row in rows:
            await db.execute(
                "INSERT INTO product_intelligence_review_field_provenance ("
                "review_provenance_id, draft_id, product_id, field_name, source_type,"
                " evidence_kind, extraction_method, verification_status,"
                " declared_value, normalized_value, source_url, source_lane,"
                " confidence_score, claim_risk_flag, reviewer_decision, reviewer_note,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (crud._uuid(), draft_id, product_id, row.field_name, row.source_type,
                 row.evidence_kind, row.extraction_method, row.verification_status,
                 row.declared_value, row.normalized_value, row.source_url,
                 row.source_lane, row.confidence_score, row.claim_risk_flag,
                 row.reviewer_decision, row.reviewer_note, now, now),
            )
    return len(rows)


def _is_empty(target: str, value: Any) -> bool:
    """Empty for merge purposes: NULL, blank text, `[]` and `{}` all mean "nothing said"."""
    normalized = _norm(target, value)
    return normalized is None or normalized == [] or normalized == {}


def reconcile_evidence(survivor: Mapping[str, Any],
                       incoming: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Merge what the survivor is SILENT about; never overwrite what it already says.

    Returns (fields_to_write, conflicting_field_names).

    B-586-04 forbids resolving a duplicate by deletion, so the losing evidence has to go
    somewhere. Two cases, and only two:
      * survivor empty, incoming has a value -> safe to adopt; nothing is lost either way.
      * both hold DIFFERENT values           -> a genuine disagreement. Auto-picking one
        would silently destroy a human-reviewable difference, so neither is written and
        the field is reported instead. The losing row is retained as SUPERSEDED with its
        provenance intact, which is where the unadopted value stays readable.
    """
    writes: dict[str, Any] = {}
    conflicts: list[str] = []
    for target in _DIGEST_TARGETS:
        if target not in incoming:
            continue
        incoming_value = _norm(target, incoming.get(target))
        if incoming_value is None:
            continue
        if _is_empty(target, survivor.get(target)):
            writes[target] = incoming.get(target)
        elif _norm(target, survivor.get(target)) != incoming_value:
            conflicts.append(target)
    return writes, conflicts


async def _open_draft_row(product_id: str) -> dict | None:
    row, _terminal = await _latest_open_draft(product_id)
    return row


async def _reconcile_lost_race(product_id: str, payload: Mapping[str, Any]) -> dict | None:
    """Another connection created this product's open draft first; adopt theirs.

    B-586-04. The DB now REJECTS the second open draft outright, so the loser holds no
    row to clean up — there is nothing to delete and no cleanup rule that could reach a
    rival's committed work. The loser's job is only to make sure its evidence is not
    thrown away: it merges the fields the winner left empty and leaves genuine
    disagreements for a human.
    """
    from agent.db import crud

    survivor = await _open_draft_row(product_id)
    if survivor is None:
        return None
    writes, conflicts = reconcile_evidence(survivor, payload.get("fields") or {})
    if writes:
        await crud.update_product_intelligence_review_draft(
            str(survivor["draft_id"]), **writes)
    return {"draft_id": str(survivor["draft_id"]), "merged_fields": sorted(writes),
            "conflicting_fields": conflicts}


def _is_open_draft_conflict(exc: BaseException) -> bool:
    """Is this the one-open-draft-per-product UNIQUE index rejecting a second row?

    Matched on the index's own column signature rather than on the exception type alone,
    so an unrelated integrity error is never swallowed as "someone else won the race".
    """
    import sqlite3

    if not isinstance(exc, sqlite3.IntegrityError):
        return False
    message = str(exc).upper()
    return ("UNIQUE" in message
            and "PRODUCT_INTELLIGENCE_REVIEW_DRAFT.PRODUCT_ID" in message)


# B-586-03. `_draft_ids_for` / `_compensate_to` / `_write_provenance_or_compensate` are
# GONE. They existed only because the draft write and the provenance write were separate
# transactions, and they had two defects no amount of tuning could fix:
#
#   * the cleanup was scoped by PRODUCT, so it could not distinguish its own partial work
#     from a concurrent request's COMMITTED work and would delete the rival's draft;
#   * the "restore" replayed a hand-listed subset of columns, so material evidence,
#     timestamps and any column not on that list silently kept the failed operation's
#     values instead of the before-state.
#
# `atomic()` removes the need for both: on failure nothing was ever committed, so the
# before-state is restored in full by definition — every column, every provenance row —
# and a rollback can only ever discard this boundary's own statements.


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
    from agent.db.schema import atomic
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
        # The approved-snapshot branch leaked: it compared material values only, so
        # stronger provenance arriving AFTER approval was returned as NOOP without ever
        # consulting verification strength. Provenance is keyed by product, so the
        # product-wide rows are the right comparison set for a snapshot.
        approved_covered = (
            material_is_covered(approved, payload_material)
            and await _approved_snapshot_provenance_covers(approved, draft, payload))
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
        # B-586-03: the draft mutation and its provenance are ONE transaction. A failure
        # anywhere inside rolls both back, so the draft keeps every one of its prior
        # values — including material evidence and timestamps — and every provenance row
        # it already had. Nothing is deleted and nothing is "restored" field by field.
        async with atomic():
            updated = await svc.update_review_draft(
                str(open_draft["draft_id"]),
                ProductIntelligenceReviewDraftUpdateRequest(
                    **build_create_request(payload).model_dump(exclude_unset=True)),
            )
            draft_id = getattr(updated, "draft_id", open_draft["draft_id"])
            update_provenance_rows = await _write_provenance(
                str(draft_id), product_id, draft, payload)
        return {"outcome": UPDATED_REVIEW_REQUIRED, "lane": lane,
                "product_id": product_id, "evidence_digest": incoming,
                "intelligence_draft_id": draft_id,
                "review_status": getattr(updated, "review_status", None),
                "provenance_rows": update_provenance_rows,
                "promoted_fields": [p["target"] for p in payload["promoted_fields"]],
                "dropped_fields": payload["dropped_fields"], "wrote": True}

    if terminal_seen and minimal:
        # Every draft is terminal and there is nothing new — leave the decision alone.
        return {"outcome": SKIPPED_TERMINAL_DRAFT, "lane": lane,
                "product_id": product_id, "evidence_digest": incoming,
                "intelligence_draft_id": None, "wrote": False}

    try:
        async with atomic():
            created = await svc.create_review_draft(
                product_id, build_create_request(payload))
            draft_id = getattr(created, "draft_id", None)
            provenance_rows = await _write_provenance(
                str(draft_id), product_id, draft, payload) if draft_id else 0
    except Exception as exc:
        # B-586-04: the DATABASE now settles the race. The losing INSERT is rejected
        # outright and its whole transaction rolls back, so there is no loser row to
        # clean up and no cleanup rule that could reach the winner's committed work.
        if not _is_open_draft_conflict(exc):
            raise
        reconciled = await _reconcile_lost_race(product_id, payload)
        if reconciled is None:
            raise
        return {"outcome": NOOP_DRAFT_UP_TO_DATE, "lane": lane,
                "product_id": product_id, "evidence_digest": incoming,
                "material_digest": incoming_material,
                "intelligence_draft_id": reconciled["draft_id"],
                "reason": "CONVERGED_ON_CONCURRENT_DRAFT",
                "merged_fields": reconciled["merged_fields"],
                "conflicting_fields": reconciled["conflicting_fields"],
                "wrote": bool(reconciled["merged_fields"])}
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
        "provenance_rows": provenance_rows,
        "wrote": True,
    }
