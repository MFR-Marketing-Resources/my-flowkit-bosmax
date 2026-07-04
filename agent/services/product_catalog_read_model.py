"""Product Truth Gateway / ProductCatalogReadModel.

ONE auditable resolver that normalises product state across every lane the
BOSMAX product pipeline exposes:

    FastMoss reference row  (``fastmoss-ref:*``, reference_only=True)
      -> bulk queue row      (``fastmoss_bulk_draft_status`` keyed by reference_id)
      -> review draft         (``draft_id``)
      -> promotion status     (READY_FOR_APPROVAL / CLAIM_RISK / ...)
      -> committed product    (``committed_product_id`` on the queue row)
      -> canonical product    (``product`` table, ``fastmoss_reference_id`` back-link)

Before this module the three consumer surfaces (Products / Sales Analyzer via
``/api/products``, BOSMAX authority via ``/api/bosmax-authority/prompt-tool-context``
and the Product Asset Generator preview) each resolved product identity through a
*different* code path, so the same id could be visible on one surface and
``PRODUCT_NOT_FOUND`` on another. This gateway gives every surface ONE
lifecycle-aware view of the same identifier.

Design rules (fail-closed, no truth invention):
  * Reference-only rows are NEVER reported as canonical.
  * READY_FOR_APPROVAL is preview-only — ``production_allowed`` stays False until a
    committed canonical product row exists.
  * Claim-risk / missing-field queue rows are reported BLOCKED, never ready.
  * Unknown ids resolve to ``PRODUCT_CONTEXT_NOT_FOUND`` — never silently coerced
    into a canonical row.
  * This module is READ-ONLY. It never writes, never mutates, never persists.
"""

from __future__ import annotations

from typing import Any, Iterable

from agent.db import crud

# ── Lifecycle states (the normalized product_state vocabulary) ──────────────
PRODUCT_STATE_REFERENCE_ONLY = "REFERENCE_ONLY"
PRODUCT_STATE_PENDING_DRAFT = "PENDING_DRAFT"
PRODUCT_STATE_READY_FOR_APPROVAL = "READY_FOR_APPROVAL_PREVIEW_ONLY"
PRODUCT_STATE_APPROVED_CANONICAL = "APPROVED_CANONICAL"
PRODUCT_STATE_DUPLICATE_LINKED = "DUPLICATE_LINKED"
PRODUCT_STATE_BLOCKED_CLAIM_RISK = "BLOCKED_CLAIM_RISK"
PRODUCT_STATE_BLOCKED_MISSING_REQUIRED_FIELD = "BLOCKED_MISSING_REQUIRED_FIELD"
PRODUCT_STATE_CONTEXT_NOT_FOUND = "PRODUCT_CONTEXT_NOT_FOUND"
PRODUCT_STATE_RUNTIME_STORAGE_UNVERIFIED = "RUNTIME_STORAGE_UNVERIFIED"

# canonical_status vocabulary (separate axis from lifecycle state)
CANONICAL_STATUS_CANONICAL = "CANONICAL"
CANONICAL_STATUS_NOT_CANONICAL = "NOT_CANONICAL"

# Queue promotion_status -> lifecycle state (no committed product yet).
_QUEUE_STATUS_TO_STATE: dict[str, str] = {
    "READY_FOR_APPROVAL": PRODUCT_STATE_READY_FOR_APPROVAL,
    "PENDING_DRAFT": PRODUCT_STATE_PENDING_DRAFT,
    "DRAFT_GENERATED": PRODUCT_STATE_PENDING_DRAFT,
    "NEEDS_REVIEW": PRODUCT_STATE_BLOCKED_CLAIM_RISK,
    "CLAIM_RISK": PRODUCT_STATE_BLOCKED_CLAIM_RISK,
    "DUPLICATE_SUSPECTED": PRODUCT_STATE_BLOCKED_CLAIM_RISK,
    "DUPLICATE_LINKED": PRODUCT_STATE_DUPLICATE_LINKED,
    "MISSING_REQUIRED_FIELD": PRODUCT_STATE_BLOCKED_MISSING_REQUIRED_FIELD,
    "IMAGE_MISSING": PRODUCT_STATE_BLOCKED_MISSING_REQUIRED_FIELD,
    "REJECTED": PRODUCT_STATE_BLOCKED_MISSING_REQUIRED_FIELD,
}


def _view(
    *,
    product_state: str,
    identifier: str,
    product_id: str | None = None,
    reference_id: str | None = None,
    draft_id: str | None = None,
    committed_product_id: str | None = None,
    source: str | None = None,
    source_lane: str | None = None,
    reference_only: bool = False,
    canonical_status: str = CANONICAL_STATUS_NOT_CANONICAL,
    preview_allowed: bool = False,
    production_allowed: bool = False,
    authority_context_available: bool = False,
    preview_resolvable: bool = False,
    blocked_reason: str | None = None,
    mapping_summary: dict[str, Any] | None = None,
    claim_gate_summary: dict[str, Any] | None = None,
    image_readiness_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the normalized product-state object. Every surface reads THIS
    shape — never re-derives identity locally."""
    return {
        "product_state": product_state,
        "identifier": identifier,
        "product_id": product_id,
        "reference_id": reference_id,
        "draft_id": draft_id,
        "committed_product_id": committed_product_id,
        "source": source,
        "source_lane": source_lane,
        "reference_only": reference_only,
        "canonical_status": canonical_status,
        "preview_allowed": preview_allowed,
        "production_allowed": production_allowed,
        "authority_context_available": authority_context_available,
        "preview_resolvable": preview_resolvable,
        "blocked_reason": blocked_reason,
        "mapping_summary": mapping_summary or {},
        "claim_gate_summary": claim_gate_summary or {},
        "image_readiness_summary": image_readiness_summary or {},
    }


def _mapping_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "category": row.get("category"),
        "subcategory": row.get("subcategory"),
        "type": row.get("type"),
        "group": row.get("group"),
        "sub_group": row.get("sub_group"),
        "type_of_product": row.get("type_of_product"),
        "bosmax_product_family": row.get("bosmax_product_family"),
        "product_type": row.get("product_type"),
        "product_type_id": row.get("product_type_id"),
        "mapping_source": row.get("mapping_source"),
        "mapping_status": row.get("mapping_status"),
        "intelligence_confidence": row.get("intelligence_confidence")
        or row.get("mapping_confidence"),
    }


def _claim_gate_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "claim_gate": row.get("claim_gate"),
        "claim_risk_level": row.get("claim_risk_level"),
        "copy_route": row.get("copy_route"),
    }


def _image_readiness_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "image_readiness_status": row.get("image_readiness_status")
        or row.get("image_asset_status")
        or row.get("image_readiness"),
        "prompt_readiness_status": row.get("prompt_readiness_status"),
        "asset_status": row.get("asset_status"),
    }


def _canonical_view(
    product: dict[str, Any],
    *,
    identifier: str,
    authority_ids: set[str] | None,
    reference_id: str | None = None,
    draft_id: str | None = None,
) -> dict[str, Any]:
    """A committed ``product`` row is the only canonical truth. Its own
    ``fastmoss_reference_id`` re-exposes the reference lineage even when the
    caller looked it up by the canonical UUID."""
    pid = product.get("id")
    ref = reference_id or product.get("fastmoss_reference_id")
    authority_available = authority_ids is None or (pid in authority_ids)
    return _view(
        product_state=PRODUCT_STATE_APPROVED_CANONICAL,
        identifier=identifier,
        product_id=pid,
        reference_id=ref,
        draft_id=draft_id,
        committed_product_id=pid,
        source=product.get("source"),
        source_lane=product.get("source_lane") or product.get("mapping_source"),
        reference_only=False,
        canonical_status=CANONICAL_STATUS_CANONICAL,
        preview_allowed=True,
        production_allowed=True,
        authority_context_available=bool(authority_available),
        preview_resolvable=True,
        blocked_reason=None,
        mapping_summary=_mapping_summary(product),
        claim_gate_summary=_claim_gate_summary(product),
        image_readiness_summary=_image_readiness_summary(product),
    )


def _reference_view(ref: dict[str, Any], *, identifier: str) -> dict[str, Any]:
    """A FastMoss reference row is visible for review but is NOT canonical: it
    has no ``product_id``, so the preview resolver (``crud.get_product``) cannot
    resolve it and production is forbidden until it is registered/committed."""
    return _view(
        product_state=PRODUCT_STATE_REFERENCE_ONLY,
        identifier=identifier,
        product_id=None,
        reference_id=ref.get("id") or identifier,
        source=ref.get("source"),
        source_lane=ref.get("source_lane"),
        reference_only=True,
        canonical_status=CANONICAL_STATUS_NOT_CANONICAL,
        preview_allowed=True,  # may be inspected in a preview-only surface
        production_allowed=False,  # never production-generate a reference row
        authority_context_available=False,
        preview_resolvable=False,  # crud.get_product will NOT resolve a ref id
        blocked_reason="REFERENCE_ONLY_REQUIRES_REGISTRATION",
        mapping_summary=_mapping_summary(ref),
        claim_gate_summary=_claim_gate_summary(ref),
        image_readiness_summary=_image_readiness_summary(ref),
    )


def _queue_view(queue: dict[str, Any], ref: dict[str, Any] | None) -> dict[str, Any]:
    """A queue row that has NOT yet produced a committed product. Promotion
    status decides the lifecycle state; production stays forbidden."""
    reference_id = queue.get("reference_id")
    status = (queue.get("promotion_status") or "PENDING_DRAFT").upper()
    state = _QUEUE_STATUS_TO_STATE.get(status, PRODUCT_STATE_PENDING_DRAFT)
    blocked_reason = None
    if state in {
        PRODUCT_STATE_BLOCKED_CLAIM_RISK,
        PRODUCT_STATE_BLOCKED_MISSING_REQUIRED_FIELD,
    }:
        blocked_reason = f"QUEUE_STATUS_{status}"
    source_row = ref or queue
    return _view(
        product_state=state,
        identifier=reference_id,
        product_id=None,
        reference_id=reference_id,
        draft_id=queue.get("draft_id"),
        committed_product_id=None,
        source=(ref or {}).get("source") or "FASTMOSS",
        source_lane=(ref or {}).get("source_lane") or "FASTMOSS_REFERENCE",
        reference_only=True,
        canonical_status=CANONICAL_STATUS_NOT_CANONICAL,
        preview_allowed=True,
        production_allowed=False,
        authority_context_available=False,
        preview_resolvable=False,
        blocked_reason=blocked_reason,
        mapping_summary=_mapping_summary(source_row),
        claim_gate_summary=_claim_gate_summary({**source_row, **queue}),
        image_readiness_summary=_image_readiness_summary({**source_row, **queue}),
    )


async def _load_reference_index() -> dict[str, dict[str, Any]]:
    """Return ``{reference_id: reference_row}``. Fail-soft: a missing FastMoss
    workbook (common in test/CI) yields an empty index, never an exception."""
    try:
        from agent.services.fastmoss_product_reference_service import (
            list_fastmoss_reference_products,
        )

        refs = await list_fastmoss_reference_products(limit=2000)
    except Exception:
        return {}
    index: dict[str, dict[str, Any]] = {}
    for ref in refs:
        rid = ref.get("id")
        if rid:
            index[rid] = ref
    return index


async def resolve_product_state(
    identifier: str,
    *,
    authority_ids: set[str] | None = None,
    reference_index: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve ONE identifier (canonical UUID or ``fastmoss-ref:*``) to the
    single normalized product-state view every surface should trust.

    ``authority_ids`` (optional): the set of product ids the BOSMAX authority
    registry can build a context for. When provided, canonical rows report
    ``authority_context_available`` truthfully, so a silent authority/catalog
    disagreement becomes visible instead of hidden.
    """
    identifier = str(identifier or "").strip()
    if not identifier:
        return _view(
            product_state=PRODUCT_STATE_CONTEXT_NOT_FOUND,
            identifier=identifier,
            blocked_reason="EMPTY_IDENTIFIER",
        )

    # 1) Canonical committed product row (authoritative truth).
    product = await crud.get_product(identifier)
    if product:
        return _canonical_view(
            product, identifier=identifier, authority_ids=authority_ids
        )

    # 2) Bulk queue row keyed by reference_id (may point forward to a product).
    queue = await crud.get_bulk_queue_row(identifier)
    if reference_index is None:
        reference_index = await _load_reference_index()
    ref = reference_index.get(identifier)

    if queue:
        committed_id = queue.get("committed_product_id")
        if committed_id:
            committed = await crud.get_product(committed_id)
            if committed:
                return _canonical_view(
                    committed,
                    identifier=identifier,
                    authority_ids=authority_ids,
                    reference_id=queue.get("reference_id"),
                    draft_id=queue.get("draft_id"),
                )
            # Queue says APPROVED but the canonical row is not in THIS storage —
            # the classic runtime-storage-binding split. Report it, do not fake it.
            view = _queue_view(queue, ref)
            view["product_state"] = PRODUCT_STATE_RUNTIME_STORAGE_UNVERIFIED
            view["committed_product_id"] = committed_id
            view["blocked_reason"] = "COMMITTED_PRODUCT_NOT_IN_ACTIVE_STORAGE"
            return view
        return _queue_view(queue, ref)

    # 3) Reference-only row (visible for review, not canonical).
    if ref:
        return _reference_view(ref, identifier=identifier)

    # 4) Nothing resolves this identifier anywhere.
    return _view(
        product_state=PRODUCT_STATE_CONTEXT_NOT_FOUND,
        identifier=identifier,
        blocked_reason="NO_LINEAGE_FOR_IDENTIFIER",
    )


async def resolve_product_states(
    identifiers: Iterable[str],
    *,
    authority_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Batch resolver — shares one reference index across the whole request."""
    reference_index = await _load_reference_index()
    out: list[dict[str, Any]] = []
    for identifier in identifiers:
        out.append(
            await resolve_product_state(
                identifier,
                authority_ids=authority_ids,
                reference_index=reference_index,
            )
        )
    return out
