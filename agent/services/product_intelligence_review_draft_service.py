from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from agent.db import crud
from agent.db.schema import _db_lock, get_db
from agent.models.product_intelligence_review_draft import (
    ProductIntelligenceReviewDraft,
    ProductIntelligenceReviewDraftApproveRequest,
    ProductIntelligenceReviewDraftCreateRequest,
    ProductIntelligenceReviewDraftListResponse,
    ProductIntelligenceReviewDraftRejectRequest,
    ProductIntelligenceReviewDraftUpdateRequest,
    ProductIntelligenceReviewDraftValidationResponse,
    ProductIntelligenceReviewFieldProvenance,
    ProductIntelligenceReviewFieldProvenanceInput,
    ReviewDraftStatus,
)
from agent.models.product_intelligence_snapshot import ProductIntelligenceSnapshot
from agent.services.product_intelligence_claim_safety_service import (
    evaluate_claim_safety,
)


REQUIRED_FIELDS = (
    "product_description",
    "benefits_json",
    "usp_json",
    "usage_text",
    "ingredients_text",
    "warnings_text",
    "target_customer_text",
    "allowed_claims_json",
    "buyer_persona_snapshot_json",
    "copy_strategy_summary_json",
    "source_urls_json",
    "image_evidence_json",
    "claim_gate",
    "claim_risk_level",
)

JSON_LIST_FIELDS = (
    "benefits_json",
    "usp_json",
    "claim_tokens_json",
    "allowed_claims_json",
    "blocked_claims_json",
)
JSON_DICT_FIELDS = (
    "source_urls_json",
    "image_evidence_json",
    "buyer_persona_snapshot_json",
    "copy_strategy_summary_json",
)
TEXT_FIELDS = (
    "product_description",
    "usage_text",
    "ingredients_text",
    "warnings_text",
    "target_customer_text",
    "paste_anything_summary",
    "package_notes",
    "size_or_volume",
    "product_form_factor",
    "packaging_description",
    "product_truth_lock",
    "reviewer_note",
    "created_by",
    "reviewed_by",
    "approved_by",
    "approved_at",
    "rejected_by",
    "rejected_at",
    "claim_gate",
    "claim_risk_level",
    "readiness_status",
)
PROVENANCE_AUTO_FIELDS = (
    "product_description",
    "benefits_json",
    "usp_json",
    "usage_text",
    "ingredients_text",
    "warnings_text",
    "target_customer_text",
    "paste_anything_summary",
    "source_urls_json",
    "image_evidence_json",
    "package_notes",
    "size_or_volume",
    "product_form_factor",
    "packaging_description",
    "product_truth_lock",
    "allowed_claims_json",
    "blocked_claims_json",
    "buyer_persona_snapshot_json",
    "copy_strategy_summary_json",
)
MEANINGFUL_CONTENT_FIELDS = (
    "product_description",
    "benefits_json",
    "usp_json",
    "usage_text",
    "ingredients_text",
    "warnings_text",
    "target_customer_text",
    "paste_anything_summary",
    "allowed_claims_json",
    "buyer_persona_snapshot_json",
    "copy_strategy_summary_json",
)
TERMINAL_STATUSES = {"APPROVED", "REJECTED"}


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_json_field(
    raw: Any,
    *,
    default: list[Any] | dict[str, Any],
    expected_type: type[list] | type[dict],
) -> list[Any] | dict[str, Any]:
    fallback = deepcopy(default)
    if raw is None or raw == "":
        return fallback
    if isinstance(raw, expected_type):
        return raw
    if not isinstance(raw, str):
        return fallback
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return fallback
    return parsed if isinstance(parsed, expected_type) else fallback


def _serialize_json(value: Any, fallback: list[Any] | dict[str, Any]) -> str:
    return json.dumps(value if value is not None else fallback)


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


def _normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _normalize_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return {
            str(key): item
            for key, item in value.items()
            if _has_value(item)
        }
    return {}


def _stringify_value(value: Any) -> str | None:
    if not _has_value(value):
        return None
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=True)


def _row_to_provenance(row: dict[str, Any]) -> ProductIntelligenceReviewFieldProvenance:
    return ProductIntelligenceReviewFieldProvenance.model_validate(row)


def _row_to_draft(
    row: dict[str, Any],
    *,
    provenance_items: list[ProductIntelligenceReviewFieldProvenance] | None = None,
) -> ProductIntelligenceReviewDraft:
    payload = dict(row)
    payload["benefits_json"] = _parse_json_field(
        payload.get("benefits_json"),
        default=[],
        expected_type=list,
    )
    payload["usp_json"] = _parse_json_field(
        payload.get("usp_json"),
        default=[],
        expected_type=list,
    )
    payload["source_urls_json"] = _parse_json_field(
        payload.get("source_urls_json"),
        default={},
        expected_type=dict,
    )
    payload["image_evidence_json"] = _parse_json_field(
        payload.get("image_evidence_json"),
        default={},
        expected_type=dict,
    )
    payload["claim_tokens_json"] = _parse_json_field(
        payload.get("claim_tokens_json"),
        default=[],
        expected_type=list,
    )
    payload["allowed_claims_json"] = _parse_json_field(
        payload.get("allowed_claims_json"),
        default=[],
        expected_type=list,
    )
    payload["blocked_claims_json"] = _parse_json_field(
        payload.get("blocked_claims_json"),
        default=[],
        expected_type=list,
    )
    payload["buyer_persona_snapshot_json"] = _parse_json_field(
        payload.get("buyer_persona_snapshot_json"),
        default={},
        expected_type=dict,
    )
    payload["copy_strategy_summary_json"] = _parse_json_field(
        payload.get("copy_strategy_summary_json"),
        default={},
        expected_type=dict,
    )
    payload["provenance_items"] = provenance_items or []
    return ProductIntelligenceReviewDraft.model_validate(payload)


async def _load_provenance_for_draft(
    draft_id: str,
) -> list[ProductIntelligenceReviewFieldProvenance]:
    rows = await crud.list_product_intelligence_review_field_provenance(draft_id=draft_id)
    return [_row_to_provenance(row) for row in rows]


async def _get_product_or_raise(product_id: str) -> dict[str, Any]:
    product = await crud.get_product(product_id)
    if not product:
        raise ValueError("PRODUCT_NOT_FOUND")
    return product


async def _get_draft_row_or_raise(draft_id: str) -> dict[str, Any]:
    row = await crud.get_product_intelligence_review_draft(draft_id)
    if not row:
        raise ValueError("DRAFT_NOT_FOUND")
    return row


def _seed_payload_from_product(product: dict[str, Any]) -> dict[str, Any]:
    # Image evidence from the product record.
    image_evidence_json: dict[str, Any] = {}
    if _has_value(product.get("image_url")):
        image_evidence_json["image_url"] = product["image_url"]
    if _has_value(product.get("local_image_path")):
        image_evidence_json["local_image_path"] = product["local_image_path"]
    image_evidence_available = bool(image_evidence_json)

    # Source provenance. Prefer a real external URL; otherwise auto-record the internal
    # product record as provenance so a MANUAL product (no external URL) is never left
    # with an empty required field it cannot legitimately fill by hand. source_urls_json
    # is required by the approval gate and MUST NOT be empty when the product row exists.
    source_urls_json: dict[str, Any] = {}
    if _has_value(product.get("source_url")):
        source_urls_json["source_url"] = product["source_url"]
    if _has_value(product.get("tiktok_product_url")):
        source_urls_json["tiktok_product_url"] = product["tiktok_product_url"]
    if not source_urls_json:
        product_name = (
            str(
                product.get("product_display_name")
                or product.get("product_short_name")
                or product.get("raw_product_title")
                or ""
            ).strip()
            or None
        )
        source_urls_json = {
            "source_type": "MANUAL_PRODUCT_RECORD",
            "product_id": product.get("id"),
            "product_name": product_name,
            "local_image_path": product.get("local_image_path") or None,
            "image_evidence_available": image_evidence_available,
        }

    return {
        "source_urls_json": source_urls_json,
        "image_evidence_json": image_evidence_json,
        "claim_risk_level": str(product.get("claim_risk_level") or "").strip() or None,
    }


def _normalize_mutation_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    for field_name in JSON_LIST_FIELDS:
        if field_name in normalized:
            normalized[field_name] = _normalize_list(normalized[field_name])
    for field_name in JSON_DICT_FIELDS:
        if field_name in normalized:
            normalized[field_name] = _normalize_dict(normalized[field_name])
    for field_name in TEXT_FIELDS:
        if field_name not in normalized:
            continue
        value = normalized[field_name]
        if value is None:
            continue
        normalized[field_name] = str(value).strip() or None
    return normalized


def _build_auto_provenance_items(
    *,
    draft_id: str,
    product_id: str,
    payload: dict[str, Any],
) -> list[ProductIntelligenceReviewFieldProvenanceInput]:
    items: list[ProductIntelligenceReviewFieldProvenanceInput] = []
    for field_name in PROVENANCE_AUTO_FIELDS:
        value = payload.get(field_name)
        if not _has_value(value):
            continue
        items.append(
            ProductIntelligenceReviewFieldProvenanceInput(
                field_name=field_name,
                declared_value=_stringify_value(value),
                normalized_value=_stringify_value(value),
                source_type="REVIEW_DRAFT",
                source_url=(
                    payload.get("source_urls_json", {}).get("source_url")
                    if isinstance(payload.get("source_urls_json"), dict)
                    else None
                ),
                source_lane="PRODUCT_INTELLIGENCE_REVIEW_DRAFT",
                evidence_kind="JSON" if isinstance(value, (list, dict)) else "TEXT",
                extraction_method="MANUAL_REVIEW",
                confidence_score=payload.get("confidence_score"),
                verification_status="PENDING_REVIEW",
                claim_risk_flag=payload.get("claim_risk_level"),
                reviewer_note=payload.get("reviewer_note"),
            ),
        )
    return items


def _evaluate_validation_payload(
    payload: dict[str, Any],
) -> dict[str, Any]:
    claim = evaluate_claim_safety(payload)
    payload.update(claim)
    missing_required_fields = [
        field_name for field_name in REQUIRED_FIELDS if not _has_value(payload.get(field_name))
    ]
    present_required_fields = [
        field_name for field_name in REQUIRED_FIELDS if field_name not in missing_required_fields
    ]
    completeness_score = round(
        len(present_required_fields) / len(REQUIRED_FIELDS),
        4,
    )
    approval_blockers: list[str] = []
    readiness_status = "READY_FOR_APPROVAL"
    if missing_required_fields:
        readiness_status = "MISSING_REQUIRED_FIELDS"
        approval_blockers.append(
            f"MISSING_REQUIRED_FIELDS:{','.join(missing_required_fields)}",
        )
    if payload["claim_gate"] == "CLAIM_BLOCKED":
        readiness_status = "CLAIM_BLOCKED"
        approval_blockers.append(
            f"CLAIM_BLOCKED:{','.join(payload['claim_tokens_json']) or 'UNSPECIFIED'}",
        )
    elif payload["claim_gate"] == "CLAIM_REVIEW_REQUIRED" and readiness_status == "READY_FOR_APPROVAL":
        readiness_status = "CLAIM_REVIEW_REQUIRED"
        approval_blockers.append(
            f"CLAIM_REVIEW_REQUIRED:{','.join(payload['claim_tokens_json']) or 'UNSPECIFIED'}",
        )
    payload["completeness_score"] = completeness_score
    payload["readiness_status"] = readiness_status
    return {
        "missing_required_fields": missing_required_fields,
        "present_required_fields": present_required_fields,
        "completeness_score": completeness_score,
        "readiness_status": readiness_status,
        "claim_gate": payload["claim_gate"],
        "claim_risk_level": payload["claim_risk_level"],
        "claim_tokens_json": payload["claim_tokens_json"],
        "allowed_claims_json": payload["allowed_claims_json"],
        "blocked_claims_json": payload["blocked_claims_json"],
        "approval_blockers": approval_blockers,
    }


def _derive_review_status(
    payload: dict[str, Any],
    *,
    current_status: str | None,
) -> ReviewDraftStatus:
    if current_status in TERMINAL_STATUSES:
        return current_status  # type: ignore[return-value]
    if not any(_has_value(payload.get(field_name)) for field_name in MEANINGFUL_CONTENT_FIELDS):
        return "DRAFT"
    if payload.get("readiness_status") == "READY_FOR_APPROVAL":
        return "READY_FOR_REVIEW"
    return "NEEDS_REVISION"


async def _replace_draft_provenance(
    *,
    draft_id: str,
    product_id: str,
    items: list[ProductIntelligenceReviewFieldProvenanceInput],
) -> None:
    await crud.delete_product_intelligence_review_field_provenance_for_draft(draft_id)
    for item in items:
        await crud.create_product_intelligence_review_field_provenance(
            draft_id=draft_id,
            product_id=product_id,
            field_name=item.field_name,
            source_type=item.source_type,
            evidence_kind=item.evidence_kind,
            extraction_method=item.extraction_method,
            verification_status=item.verification_status,
            declared_value=item.declared_value,
            normalized_value=item.normalized_value,
            source_url=item.source_url,
            source_lane=item.source_lane,
            confidence_score=item.confidence_score,
            claim_risk_flag=item.claim_risk_flag,
            reviewer_decision=item.reviewer_decision,
            reviewer_note=item.reviewer_note,
        )


async def get_review_draft_by_id(
    draft_id: str,
) -> ProductIntelligenceReviewDraft | None:
    row = await crud.get_product_intelligence_review_draft(draft_id)
    if not row:
        return None
    provenance_items = await _load_provenance_for_draft(draft_id)
    return _row_to_draft(row, provenance_items=provenance_items)


async def create_review_draft(
    product_id: str,
    request: ProductIntelligenceReviewDraftCreateRequest,
) -> ProductIntelligenceReviewDraft:
    product = await _get_product_or_raise(product_id)
    payload = _seed_payload_from_product(product)
    payload.update(request.model_dump(exclude_unset=True))
    payload = _normalize_mutation_payload(payload)
    validation = _evaluate_validation_payload(payload)
    review_status = _derive_review_status(payload, current_status=None)
    row = await crud.create_product_intelligence_review_draft(
        product_id=product_id,
        review_status=review_status,
        product_description=payload.get("product_description"),
        benefits_json=_serialize_json(payload.get("benefits_json"), []),
        usp_json=_serialize_json(payload.get("usp_json"), []),
        usage_text=payload.get("usage_text"),
        ingredients_text=payload.get("ingredients_text"),
        warnings_text=payload.get("warnings_text"),
        target_customer_text=payload.get("target_customer_text"),
        paste_anything_summary=payload.get("paste_anything_summary"),
        source_urls_json=_serialize_json(payload.get("source_urls_json"), {}),
        image_evidence_json=_serialize_json(payload.get("image_evidence_json"), {}),
        package_notes=payload.get("package_notes"),
        size_or_volume=payload.get("size_or_volume"),
        product_form_factor=payload.get("product_form_factor"),
        packaging_description=payload.get("packaging_description"),
        product_truth_lock=payload.get("product_truth_lock"),
        claim_gate=validation["claim_gate"],
        claim_risk_level=validation["claim_risk_level"],
        claim_tokens_json=_serialize_json(validation["claim_tokens_json"], []),
        allowed_claims_json=_serialize_json(validation["allowed_claims_json"], []),
        blocked_claims_json=_serialize_json(validation["blocked_claims_json"], []),
        buyer_persona_snapshot_json=_serialize_json(
            payload.get("buyer_persona_snapshot_json"),
            {},
        ),
        copy_strategy_summary_json=_serialize_json(
            payload.get("copy_strategy_summary_json"),
            {},
        ),
        confidence_score=payload.get("confidence_score"),
        completeness_score=validation["completeness_score"],
        readiness_status=validation["readiness_status"],
        reviewer_note=payload.get("reviewer_note"),
        created_by=payload.get("created_by"),
        reviewed_by=payload.get("reviewed_by"),
    )
    draft_id = str(row["draft_id"])
    provenance_items = request.provenance_items or _build_auto_provenance_items(
        draft_id=draft_id,
        product_id=product_id,
        payload=payload,
    )
    await _replace_draft_provenance(
        draft_id=draft_id,
        product_id=product_id,
        items=provenance_items,
    )
    draft = await get_review_draft_by_id(draft_id)
    if not draft:
        raise ValueError("DRAFT_NOT_FOUND")
    return draft


async def list_review_drafts(
    product_id: str,
    *,
    limit: int = 20,
) -> ProductIntelligenceReviewDraftListResponse:
    await _get_product_or_raise(product_id)
    rows = await crud.list_product_intelligence_review_drafts(product_id=product_id, limit=limit)
    items: list[ProductIntelligenceReviewDraft] = []
    for row in rows:
        draft = _row_to_draft(row)
        items.append(draft)
    return ProductIntelligenceReviewDraftListResponse(product_id=product_id, items=items)


async def update_review_draft(
    draft_id: str,
    request: ProductIntelligenceReviewDraftUpdateRequest,
) -> ProductIntelligenceReviewDraft:
    existing_row = await _get_draft_row_or_raise(draft_id)
    existing = _row_to_draft(existing_row)
    if existing.review_status in TERMINAL_STATUSES:
        raise ValueError(f"DRAFT_UPDATE_FORBIDDEN:{existing.review_status}")

    payload = existing.model_dump(exclude={"draft_id", "product_id", "created_at", "updated_at", "provenance_items"})
    payload.update(request.model_dump(exclude_unset=True))
    payload = _normalize_mutation_payload(payload)
    validation = _evaluate_validation_payload(payload)
    review_status = _derive_review_status(payload, current_status=existing.review_status)
    await crud.update_product_intelligence_review_draft(
        draft_id,
        review_status=review_status,
        product_description=payload.get("product_description"),
        benefits_json=_serialize_json(payload.get("benefits_json"), []),
        usp_json=_serialize_json(payload.get("usp_json"), []),
        usage_text=payload.get("usage_text"),
        ingredients_text=payload.get("ingredients_text"),
        warnings_text=payload.get("warnings_text"),
        target_customer_text=payload.get("target_customer_text"),
        paste_anything_summary=payload.get("paste_anything_summary"),
        source_urls_json=_serialize_json(payload.get("source_urls_json"), {}),
        image_evidence_json=_serialize_json(payload.get("image_evidence_json"), {}),
        package_notes=payload.get("package_notes"),
        size_or_volume=payload.get("size_or_volume"),
        product_form_factor=payload.get("product_form_factor"),
        packaging_description=payload.get("packaging_description"),
        product_truth_lock=payload.get("product_truth_lock"),
        claim_gate=validation["claim_gate"],
        claim_risk_level=validation["claim_risk_level"],
        claim_tokens_json=_serialize_json(validation["claim_tokens_json"], []),
        allowed_claims_json=_serialize_json(validation["allowed_claims_json"], []),
        blocked_claims_json=_serialize_json(validation["blocked_claims_json"], []),
        buyer_persona_snapshot_json=_serialize_json(
            payload.get("buyer_persona_snapshot_json"),
            {},
        ),
        copy_strategy_summary_json=_serialize_json(
            payload.get("copy_strategy_summary_json"),
            {},
        ),
        confidence_score=payload.get("confidence_score"),
        completeness_score=validation["completeness_score"],
        readiness_status=validation["readiness_status"],
        reviewer_note=payload.get("reviewer_note"),
        created_by=payload.get("created_by"),
        reviewed_by=payload.get("reviewed_by"),
    )
    provenance_items = request.provenance_items
    if provenance_items is not None:
        await _replace_draft_provenance(
            draft_id=draft_id,
            product_id=existing.product_id,
            items=provenance_items,
        )
    draft = await get_review_draft_by_id(draft_id)
    if not draft:
        raise ValueError("DRAFT_NOT_FOUND")
    return draft


async def validate_review_draft(
    draft_id: str,
) -> ProductIntelligenceReviewDraftValidationResponse:
    draft = await get_review_draft_by_id(draft_id)
    if not draft:
        raise ValueError("DRAFT_NOT_FOUND")
    if draft.review_status in TERMINAL_STATUSES:
        validation = _evaluate_validation_payload(
            draft.model_dump(exclude={"draft_id", "product_id", "created_at", "updated_at", "provenance_items"}),
        )
        return ProductIntelligenceReviewDraftValidationResponse(
            draft=draft,
            **validation,
        )

    updated = await update_review_draft(
        draft_id,
        ProductIntelligenceReviewDraftUpdateRequest(
            provenance_items=[
                ProductIntelligenceReviewFieldProvenanceInput.model_validate(
                    item.model_dump(
                        exclude={"review_provenance_id", "draft_id", "product_id", "created_at", "updated_at"},
                    ),
                )
                for item in draft.provenance_items
            ],
        ),
    )
    validation = _evaluate_validation_payload(
        updated.model_dump(exclude={"draft_id", "product_id", "created_at", "updated_at", "provenance_items"}),
    )
    return ProductIntelligenceReviewDraftValidationResponse(draft=updated, **validation)


async def reject_review_draft(
    draft_id: str,
    request: ProductIntelligenceReviewDraftRejectRequest,
) -> ProductIntelligenceReviewDraft:
    draft = await get_review_draft_by_id(draft_id)
    if not draft:
        raise ValueError("DRAFT_NOT_FOUND")
    if draft.review_status == "APPROVED":
        raise ValueError("DRAFT_ALREADY_APPROVED")
    if draft.review_status == "REJECTED":
        raise ValueError("DRAFT_ALREADY_REJECTED")
    rejected_by = (request.rejected_by or draft.reviewed_by or "operator").strip()
    await crud.update_product_intelligence_review_draft(
        draft_id,
        review_status="REJECTED",
        reviewer_note=request.reviewer_note if request.reviewer_note is not None else draft.reviewer_note,
        reviewed_by=draft.reviewed_by or rejected_by,
        rejected_by=rejected_by,
        rejected_at=_now_iso(),
    )
    updated = await get_review_draft_by_id(draft_id)
    if not updated:
        raise ValueError("DRAFT_NOT_FOUND")
    return updated


def _snapshot_from_row(row: dict[str, Any]) -> ProductIntelligenceSnapshot:
    payload = dict(row)
    payload["benefits_json"] = _parse_json_field(payload.get("benefits_json"), default=[], expected_type=list)
    payload["usp_json"] = _parse_json_field(payload.get("usp_json"), default=[], expected_type=list)
    payload["source_urls_json"] = _parse_json_field(payload.get("source_urls_json"), default={}, expected_type=dict)
    payload["image_evidence_json"] = _parse_json_field(payload.get("image_evidence_json"), default={}, expected_type=dict)
    payload["claim_tokens_json"] = _parse_json_field(payload.get("claim_tokens_json"), default=[], expected_type=list)
    payload["allowed_claims_json"] = _parse_json_field(payload.get("allowed_claims_json"), default=[], expected_type=list)
    payload["blocked_claims_json"] = _parse_json_field(payload.get("blocked_claims_json"), default=[], expected_type=list)
    payload["buyer_persona_snapshot_json"] = _parse_json_field(
        payload.get("buyer_persona_snapshot_json"),
        default={},
        expected_type=dict,
    )
    payload["copy_strategy_summary_json"] = _parse_json_field(
        payload.get("copy_strategy_summary_json"),
        default={},
        expected_type=dict,
    )
    return ProductIntelligenceSnapshot.model_validate(payload)


async def approve_review_draft(
    draft_id: str,
    request: ProductIntelligenceReviewDraftApproveRequest,
) -> ProductIntelligenceSnapshot:
    draft = await get_review_draft_by_id(draft_id)
    if not draft:
        raise ValueError("DRAFT_NOT_FOUND")
    if draft.review_status == "APPROVED":
        raise ValueError("DRAFT_ALREADY_APPROVED")
    if draft.review_status == "REJECTED":
        raise ValueError("DRAFT_ALREADY_REJECTED")
    validation = await validate_review_draft(draft_id)
    if validation.approval_blockers:
        raise ValueError(f"DRAFT_NOT_APPROVABLE:{'|'.join(validation.approval_blockers)}")

    await _get_product_or_raise(draft.product_id)
    approved_by = (request.approved_by or draft.reviewed_by or draft.created_by or "operator").strip()
    approval_note = request.approval_note if request.approval_note is not None else draft.reviewer_note
    now = _now_iso()
    db = await get_db()
    snapshot_id = str(uuid4())
    async with _db_lock:
        latest_cur = await db.execute(
            """
            SELECT * FROM product_intelligence_snapshot
            WHERE product_id=? AND status='APPROVED'
            ORDER BY version DESC, approved_at DESC, created_at DESC, snapshot_id DESC
            LIMIT 1
            """,
            (draft.product_id,),
        )
        latest_row = await latest_cur.fetchone()
        latest_snapshot = dict(latest_row) if latest_row else None

        version_cur = await db.execute(
            "SELECT COALESCE(MAX(version), 0) FROM product_intelligence_snapshot WHERE product_id=?",
            (draft.product_id,),
        )
        next_version = int((await version_cur.fetchone())[0]) + 1
        if latest_snapshot:
            await db.execute(
                """
                UPDATE product_intelligence_snapshot
                SET status='SUPERSEDED', updated_at=?
                WHERE snapshot_id=?
                """,
                (now, latest_snapshot["snapshot_id"]),
            )

        await db.execute(
            """
            INSERT INTO product_intelligence_snapshot (
                snapshot_id, product_id, version, status, product_description, benefits_json,
                usp_json, usage_text, ingredients_text, warnings_text, target_customer_text,
                paste_anything_summary, source_urls_json, image_evidence_json, package_notes,
                size_or_volume, product_form_factor, packaging_description, product_truth_lock,
                claim_gate, claim_risk_level, claim_tokens_json, allowed_claims_json,
                blocked_claims_json, buyer_persona_snapshot_json, copy_strategy_summary_json,
                confidence_score, completeness_score, readiness_status, created_from_review_draft_id,
                created_by, approved_by, approved_at, supersedes_snapshot_id, created_at, updated_at
            ) VALUES (?, ?, ?, 'APPROVED', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                draft.product_id,
                next_version,
                draft.product_description,
                json.dumps(draft.benefits_json),
                json.dumps(draft.usp_json),
                draft.usage_text,
                draft.ingredients_text,
                draft.warnings_text,
                draft.target_customer_text,
                draft.paste_anything_summary,
                json.dumps(draft.source_urls_json),
                json.dumps(draft.image_evidence_json),
                draft.package_notes,
                draft.size_or_volume,
                draft.product_form_factor,
                draft.packaging_description,
                draft.product_truth_lock,
                draft.claim_gate,
                draft.claim_risk_level,
                json.dumps(draft.claim_tokens_json),
                json.dumps(draft.allowed_claims_json),
                json.dumps(draft.blocked_claims_json),
                json.dumps(draft.buyer_persona_snapshot_json),
                json.dumps(draft.copy_strategy_summary_json),
                draft.confidence_score,
                draft.completeness_score,
                draft.readiness_status,
                draft.draft_id,
                draft.created_by,
                approved_by,
                now,
                latest_snapshot["snapshot_id"] if latest_snapshot else None,
                now,
                now,
            ),
        )

        provenance_rows = [
            item.model_dump(exclude={"review_provenance_id", "draft_id", "product_id", "created_at", "updated_at"})
            for item in draft.provenance_items
        ]
        if not provenance_rows:
            provenance_rows = [
                item.model_dump()
                for item in _build_auto_provenance_items(
                    draft_id=draft.draft_id,
                    product_id=draft.product_id,
                    payload=draft.model_dump(exclude={"draft_id", "product_id", "created_at", "updated_at", "provenance_items"}),
                )
            ]
        for item in provenance_rows:
            await db.execute(
                """
                INSERT INTO product_intelligence_field_provenance (
                    provenance_id, snapshot_id, product_id, field_name, declared_value,
                    normalized_value, source_type, source_url, source_lane, evidence_kind,
                    extraction_method, confidence_score, verification_status, claim_risk_flag,
                    reviewer_decision, reviewer_note, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    snapshot_id,
                    draft.product_id,
                    item["field_name"],
                    item.get("declared_value"),
                    item.get("normalized_value"),
                    item["source_type"],
                    item.get("source_url"),
                    item.get("source_lane"),
                    item["evidence_kind"],
                    item["extraction_method"],
                    item.get("confidence_score"),
                    "REVIEWED_APPROVED",
                    item.get("claim_risk_flag"),
                    item.get("reviewer_decision") or "APPROVED",
                    item.get("reviewer_note") or approval_note,
                    now,
                    now,
                ),
            )

        await db.execute(
            """
            UPDATE product_intelligence_review_draft
            SET review_status='APPROVED', reviewer_note=?, reviewed_by=?, approved_by=?,
                approved_at=?, updated_at=?
            WHERE draft_id=?
            """,
            (
                approval_note,
                draft.reviewed_by or approved_by,
                approved_by,
                now,
                now,
                draft.draft_id,
            ),
        )
        await db.commit()

    snapshot_row = await crud.get_product_intelligence_snapshot(snapshot_id)
    if not snapshot_row:
        raise ValueError("SNAPSHOT_NOT_FOUND")
    return _snapshot_from_row(snapshot_row)
