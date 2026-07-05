from __future__ import annotations

import json
import logging
from copy import deepcopy
from typing import Any

from agent.db import crud
from agent.models.product_intelligence_snapshot import (
    ProductIntelligenceFieldProvenance,
    ProductIntelligenceFieldProvenanceListResponse,
    ProductIntelligenceLatestSnapshotResponse,
    ProductIntelligenceProvenanceSummary,
    ProductIntelligenceSnapshot,
    ProductIntelligenceSnapshotListResponse,
)

logger = logging.getLogger(__name__)


def _parse_json_field(
    raw: Any,
    *,
    default: list[Any] | dict[str, Any],
    expected_type: type[list] | type[dict],
    field_name: str,
) -> list[Any] | dict[str, Any]:
    fallback = deepcopy(default)
    if raw is None or raw == "":
        return fallback
    if isinstance(raw, expected_type):
        return raw
    if not isinstance(raw, str):
        logger.warning(
            "Product intelligence field %s had unsupported JSON storage type %s; using fallback.",
            field_name,
            type(raw).__name__,
        )
        return fallback
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning(
            "Product intelligence field %s contained invalid JSON text; using fallback.",
            field_name,
        )
        return fallback
    if isinstance(parsed, expected_type):
        return parsed
    logger.warning(
        "Product intelligence field %s parsed to %s instead of %s; using fallback.",
        field_name,
        type(parsed).__name__,
        expected_type.__name__,
    )
    return fallback


def _row_to_snapshot(row: dict[str, Any]) -> ProductIntelligenceSnapshot:
    payload = dict(row)
    payload["benefits_json"] = _parse_json_field(
        payload.get("benefits_json"),
        default=[],
        expected_type=list,
        field_name="benefits_json",
    )
    payload["usp_json"] = _parse_json_field(
        payload.get("usp_json"),
        default=[],
        expected_type=list,
        field_name="usp_json",
    )
    payload["source_urls_json"] = _parse_json_field(
        payload.get("source_urls_json"),
        default={},
        expected_type=dict,
        field_name="source_urls_json",
    )
    payload["image_evidence_json"] = _parse_json_field(
        payload.get("image_evidence_json"),
        default={},
        expected_type=dict,
        field_name="image_evidence_json",
    )
    payload["claim_tokens_json"] = _parse_json_field(
        payload.get("claim_tokens_json"),
        default=[],
        expected_type=list,
        field_name="claim_tokens_json",
    )
    payload["allowed_claims_json"] = _parse_json_field(
        payload.get("allowed_claims_json"),
        default=[],
        expected_type=list,
        field_name="allowed_claims_json",
    )
    payload["blocked_claims_json"] = _parse_json_field(
        payload.get("blocked_claims_json"),
        default=[],
        expected_type=list,
        field_name="blocked_claims_json",
    )
    payload["buyer_persona_snapshot_json"] = _parse_json_field(
        payload.get("buyer_persona_snapshot_json"),
        default={},
        expected_type=dict,
        field_name="buyer_persona_snapshot_json",
    )
    payload["copy_strategy_summary_json"] = _parse_json_field(
        payload.get("copy_strategy_summary_json"),
        default={},
        expected_type=dict,
        field_name="copy_strategy_summary_json",
    )
    return ProductIntelligenceSnapshot.model_validate(payload)


def _row_to_provenance(row: dict[str, Any]) -> ProductIntelligenceFieldProvenance:
    return ProductIntelligenceFieldProvenance.model_validate(row)


async def create_snapshot(
    *,
    product_id: str,
    version: int,
    status: str,
    product_description: str | None = None,
    benefits_json: list[str] | None = None,
    usp_json: list[str] | None = None,
    usage_text: str | None = None,
    ingredients_text: str | None = None,
    warnings_text: str | None = None,
    target_customer_text: str | None = None,
    paste_anything_summary: str | None = None,
    source_urls_json: dict[str, Any] | None = None,
    image_evidence_json: dict[str, Any] | None = None,
    package_notes: str | None = None,
    size_or_volume: str | None = None,
    product_form_factor: str | None = None,
    packaging_description: str | None = None,
    product_truth_lock: str | None = None,
    claim_gate: str | None = None,
    claim_risk_level: str | None = None,
    claim_tokens_json: list[str] | None = None,
    allowed_claims_json: list[str] | None = None,
    blocked_claims_json: list[str] | None = None,
    buyer_persona_snapshot_json: dict[str, Any] | None = None,
    copy_strategy_summary_json: dict[str, Any] | None = None,
    confidence_score: float | None = None,
    completeness_score: float | None = None,
    readiness_status: str | None = None,
    created_from_review_draft_id: str | None = None,
    created_by: str | None = None,
    approved_by: str | None = None,
    approved_at: str | None = None,
    supersedes_snapshot_id: str | None = None,
) -> ProductIntelligenceSnapshot:
    row = await crud.create_product_intelligence_snapshot(
        product_id=product_id,
        version=version,
        status=status,
        product_description=product_description,
        benefits_json=json.dumps(benefits_json or []),
        usp_json=json.dumps(usp_json or []),
        usage_text=usage_text,
        ingredients_text=ingredients_text,
        warnings_text=warnings_text,
        target_customer_text=target_customer_text,
        paste_anything_summary=paste_anything_summary,
        source_urls_json=json.dumps(source_urls_json or {}),
        image_evidence_json=json.dumps(image_evidence_json or {}),
        package_notes=package_notes,
        size_or_volume=size_or_volume,
        product_form_factor=product_form_factor,
        packaging_description=packaging_description,
        product_truth_lock=product_truth_lock,
        claim_gate=claim_gate,
        claim_risk_level=claim_risk_level,
        claim_tokens_json=json.dumps(claim_tokens_json or []),
        allowed_claims_json=json.dumps(allowed_claims_json or []),
        blocked_claims_json=json.dumps(blocked_claims_json or []),
        buyer_persona_snapshot_json=json.dumps(buyer_persona_snapshot_json or {}),
        copy_strategy_summary_json=json.dumps(copy_strategy_summary_json or {}),
        confidence_score=confidence_score,
        completeness_score=completeness_score,
        readiness_status=readiness_status,
        created_from_review_draft_id=created_from_review_draft_id,
        created_by=created_by,
        approved_by=approved_by,
        approved_at=approved_at,
        supersedes_snapshot_id=supersedes_snapshot_id,
    )
    return _row_to_snapshot(row)


async def get_snapshot_by_id(snapshot_id: str) -> ProductIntelligenceSnapshot | None:
    row = await crud.get_product_intelligence_snapshot(snapshot_id)
    return _row_to_snapshot(row) if row else None


async def list_snapshots(
    *,
    product_id: str,
    status: str | None = None,
    limit: int | None = 20,
) -> list[ProductIntelligenceSnapshot]:
    rows = await crud.list_product_intelligence_snapshots(
        product_id=product_id,
        status=status,
        limit=limit,
    )
    return [_row_to_snapshot(row) for row in rows]


async def get_latest_approved_snapshot(
    product_id: str,
) -> ProductIntelligenceSnapshot | None:
    row = await crud.get_latest_approved_product_intelligence_snapshot(product_id)
    return _row_to_snapshot(row) if row else None


async def create_field_provenance(
    *,
    snapshot_id: str,
    product_id: str,
    field_name: str,
    source_type: str,
    evidence_kind: str,
    extraction_method: str,
    verification_status: str,
    declared_value: str | None = None,
    normalized_value: str | None = None,
    source_url: str | None = None,
    source_lane: str | None = None,
    confidence_score: float | None = None,
    claim_risk_flag: str | None = None,
    reviewer_decision: str | None = None,
    reviewer_note: str | None = None,
) -> ProductIntelligenceFieldProvenance:
    row = await crud.create_product_intelligence_field_provenance(
        snapshot_id=snapshot_id,
        product_id=product_id,
        field_name=field_name,
        source_type=source_type,
        evidence_kind=evidence_kind,
        extraction_method=extraction_method,
        verification_status=verification_status,
        declared_value=declared_value,
        normalized_value=normalized_value,
        source_url=source_url,
        source_lane=source_lane,
        confidence_score=confidence_score,
        claim_risk_flag=claim_risk_flag,
        reviewer_decision=reviewer_decision,
        reviewer_note=reviewer_note,
    )
    return _row_to_provenance(row)


async def list_field_provenance(
    *,
    snapshot_id: str | None = None,
    product_id: str | None = None,
    field_name: str | None = None,
    limit: int | None = None,
) -> list[ProductIntelligenceFieldProvenance]:
    rows = await crud.list_product_intelligence_field_provenance(
        snapshot_id=snapshot_id,
        product_id=product_id,
        field_name=field_name,
        limit=limit,
    )
    return [_row_to_provenance(row) for row in rows]


async def get_latest_snapshot_response(
    product_id: str,
) -> ProductIntelligenceLatestSnapshotResponse:
    product = await crud.get_product(product_id)
    if not product:
        raise ValueError("PRODUCT_NOT_FOUND")
    rows = await crud.list_product_intelligence_snapshots(product_id=product_id, limit=None)
    latest = await get_latest_approved_snapshot(product_id)
    approved_count = sum(1 for row in rows if row.get("status") == "APPROVED")
    summary = ProductIntelligenceProvenanceSummary(
        total_snapshots=len(rows),
        approved_snapshot_count=approved_count,
        latest_approved_snapshot_id=latest.snapshot_id if latest else None,
        latest_approved_version=latest.version if latest else None,
    )
    return ProductIntelligenceLatestSnapshotResponse(
        product_id=product_id,
        latest_snapshot=latest,
        status="APPROVED_SNAPSHOT_AVAILABLE" if latest else "NO_APPROVED_SNAPSHOT",
        provenance_summary=summary,
    )


async def get_snapshot_list_response(
    product_id: str,
    *,
    status: str | None = None,
    limit: int = 20,
) -> ProductIntelligenceSnapshotListResponse:
    product = await crud.get_product(product_id)
    if not product:
        raise ValueError("PRODUCT_NOT_FOUND")
    items = await list_snapshots(product_id=product_id, status=status, limit=limit)
    return ProductIntelligenceSnapshotListResponse(product_id=product_id, items=items)


async def get_provenance_list_response(
    snapshot_id: str,
    *,
    field_name: str | None = None,
) -> ProductIntelligenceFieldProvenanceListResponse:
    snapshot = await crud.get_product_intelligence_snapshot(snapshot_id)
    if not snapshot:
        raise ValueError("SNAPSHOT_NOT_FOUND")
    items = await list_field_provenance(snapshot_id=snapshot_id, field_name=field_name)
    return ProductIntelligenceFieldProvenanceListResponse(
        snapshot_id=snapshot_id,
        product_id=str(snapshot.get("product_id")),
        items=items,
    )
