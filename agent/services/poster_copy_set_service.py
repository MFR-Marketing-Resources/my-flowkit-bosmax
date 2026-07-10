"""Poster Copy Set lifecycle (POSTER_BUILDER_V2).

Create / edit / approve / reject / version poster-NATIVE copy sets.

Domain isolation invariants (enforced by construction):
- This module NEVER imports or touches the video `copy_set` crud/model writers.
- Statuses live in the POSTER_COPY_* namespace.
- Approval is explicit (APPROVE_POSTER_COPY_SET) and runs the MANDATORY poster
  copy-quality gate server-side — a BLOCK finding can never be attested away.
- Editing an APPROVED set never mutates it: a new version row is created and the
  parent is marked POSTER_COPY_SUPERSEDED (approved copy consumed by a render
  manifest stays immutable).
"""
from __future__ import annotations

import json
from typing import Any

from agent.db import crud
from agent.models.poster_copy_quality import PosterCopyQualityRequest
from agent.models.poster_copy_set import (
    MAX_PROOF_POINTS,
    POSTER_COPY_APPROVAL_PHRASE,
    PROVENANCE_OPERATOR,
    STATUS_POSTER_COPY_APPROVED,
    STATUS_POSTER_COPY_DRAFT,
    STATUS_POSTER_COPY_REJECTED,
    STATUS_POSTER_COPY_REVIEW_REQUIRED,
    STATUS_POSTER_COPY_SUPERSEDED,
    PosterCopySetCreateRequest,
    PosterCopySetPatchRequest,
    serialize_poster_copy_set,
    validate_poster_native_lengths,
)
from agent.services.poster_copy_quality_service import evaluate_poster_copy

_EDITABLE_STATUSES = {
    STATUS_POSTER_COPY_DRAFT,
    STATUS_POSTER_COPY_REVIEW_REQUIRED,
    STATUS_POSTER_COPY_REJECTED,
}

_TEXT_FIELDS = (
    "objective",
    "archetype",
    "angle",
    "primary_message",
    "support_message",
    "cta",
    "disclaimer",
    "tone",
    "language",
)


class PosterCopySetError(Exception):
    def __init__(self, code: str, message: str = "", *, status_code: int = 422,
                 field_errors: list[str] | None = None):
        super().__init__(message or code)
        self.code = code
        self.status_code = status_code
        self.field_errors = field_errors or []


def _norm(v: Any) -> str:
    return str(v or "").strip()


def _quality_request(fields: dict[str, Any]) -> PosterCopyQualityRequest:
    """Poster-native fields → the expert quality-guard request shape."""
    points = [_norm(p) for p in (fields.get("proof_points") or []) if _norm(p)]
    return PosterCopyQualityRequest(
        archetype=_norm(fields.get("archetype")),
        language=_norm(fields.get("language")) or "ms",
        max_chips=MAX_PROOF_POINTS,
        poster_headline=_norm(fields.get("primary_message")),
        poster_support_line=_norm(fields.get("support_message")),
        poster_chips=points,
        poster_cta=_norm(fields.get("cta")),
        product_detail_line=_norm(fields.get("disclaimer")),
    )


def run_poster_copy_gate(fields: dict[str, Any], *, strict: bool) -> list[str]:
    """Run poster-native length validation + the expert quality guard.

    Returns WARN summaries. Raises PosterCopySetError on any hard failure.
    strict=True (approval) also fails on BLOCK findings; drafts only fail on
    length/structure errors so draft capture stays fast and permissive.
    """
    errors = validate_poster_native_lengths(fields)
    if errors:
        raise PosterCopySetError(
            "POSTER_COPY_LENGTH_INVALID", "Poster copy exceeds poster-native limits",
            field_errors=errors,
        )
    report = evaluate_poster_copy(_quality_request(fields))
    blocks = [f"{x.code}: {x.message}" for x in report.findings if x.severity == "BLOCK"]
    warns = [f"{x.code}: {x.message}" for x in report.findings if x.severity == "WARN"]
    if strict and blocks:
        raise PosterCopySetError(
            "POSTER_COPY_QUALITY_BLOCKED", "Poster copy quality gate failed",
            field_errors=blocks,
        )
    if not strict and blocks:
        # Draft path: record blocks as warnings so the operator sees them early.
        warns = blocks + warns
    return warns


def _row_payload(fields: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for name in _TEXT_FIELDS:
        if name in fields and fields[name] is not None:
            payload[name] = _norm(fields[name])
    if fields.get("proof_points") is not None:
        points = [_norm(p) for p in (fields.get("proof_points") or []) if _norm(p)]
        payload["proof_points_json"] = json.dumps(points, ensure_ascii=False)
    if fields.get("offer") is not None:
        payload["offer_json"] = json.dumps(fields["offer"], ensure_ascii=False)
    if fields.get("variants") is not None:
        payload["variants_json"] = json.dumps(fields["variants"], ensure_ascii=False)
    if fields.get("field_provenance") is not None:
        payload["field_provenance_json"] = json.dumps(
            fields["field_provenance"], ensure_ascii=False
        )
    for name in ("campaign_id", "ai_model", "prompt_version"):
        if fields.get(name) is not None and name in fields:
            payload[name] = _norm(fields[name])
    return payload


class PosterCopySetService:
    @staticmethod
    async def create_draft(request: PosterCopySetCreateRequest) -> dict[str, Any]:
        product_id = _norm(request.product_id)
        if not product_id:
            raise PosterCopySetError("PRODUCT_ID_REQUIRED", status_code=422)
        product = await crud.get_product(product_id)
        if not product:
            raise PosterCopySetError("PRODUCT_NOT_FOUND", status_code=404)

        fields = request.model_dump()
        warnings = run_poster_copy_gate(fields, strict=False)
        payload = _row_payload(fields)
        payload["status"] = STATUS_POSTER_COPY_DRAFT
        payload["version"] = 1
        row = await crud.create_poster_copy_set(product_id, **payload)
        out = serialize_poster_copy_set(row)
        out["warnings"] = warnings
        return out

    @staticmethod
    async def patch_draft(
        poster_copy_set_id: str, request: PosterCopySetPatchRequest
    ) -> dict[str, Any]:
        row = await crud.get_poster_copy_set(poster_copy_set_id)
        if not row:
            raise PosterCopySetError("POSTER_COPY_SET_NOT_FOUND", status_code=404)
        if row.get("status") not in _EDITABLE_STATUSES:
            raise PosterCopySetError(
                "POSTER_COPY_SET_NOT_EDITABLE",
                "Approved poster copy is immutable — create a new version instead",
                status_code=409,
            )
        merged = serialize_poster_copy_set(row)
        patch = {k: v for k, v in request.model_dump().items() if v is not None}
        merged.update(patch)
        # Operator edits stamp field provenance for the touched copy fields.
        provenance = dict(merged.get("field_provenance") or {})
        for k in patch:
            if k in ("primary_message", "support_message", "proof_points", "cta",
                     "disclaimer"):
                provenance[k] = PROVENANCE_OPERATOR
        merged["field_provenance"] = provenance
        warnings = run_poster_copy_gate(merged, strict=False)
        payload = _row_payload(merged)
        payload["status"] = STATUS_POSTER_COPY_DRAFT
        updated = await crud.update_poster_copy_set(poster_copy_set_id, **payload)
        out = serialize_poster_copy_set(updated)
        out["warnings"] = warnings
        return out

    @staticmethod
    async def approve(
        poster_copy_set_id: str, *, approval_phrase: str, approved_by: str
    ) -> dict[str, Any]:
        if _norm(approval_phrase) != POSTER_COPY_APPROVAL_PHRASE:
            raise PosterCopySetError(
                "POSTER_COPY_APPROVAL_PHRASE_INVALID",
                f"Approval requires the explicit phrase {POSTER_COPY_APPROVAL_PHRASE}",
                status_code=422,
            )
        row = await crud.get_poster_copy_set(poster_copy_set_id)
        if not row:
            raise PosterCopySetError("POSTER_COPY_SET_NOT_FOUND", status_code=404)
        if row.get("status") == STATUS_POSTER_COPY_APPROVED:
            return serialize_poster_copy_set(row)
        if row.get("status") == STATUS_POSTER_COPY_SUPERSEDED:
            raise PosterCopySetError(
                "POSTER_COPY_SET_SUPERSEDED",
                "This version was superseded — approve the latest version",
                status_code=409,
            )
        fields = serialize_poster_copy_set(row)
        # MANDATORY strict gate — server-side, cannot be bypassed by any UI path.
        run_poster_copy_gate(fields, strict=True)
        updated = await crud.update_poster_copy_set(
            poster_copy_set_id,
            status=STATUS_POSTER_COPY_APPROVED,
            approved_at=crud._now(),
            approved_by=_norm(approved_by) or "operator",
        )
        return serialize_poster_copy_set(updated)

    @staticmethod
    async def reject(poster_copy_set_id: str, *, reason: str = "") -> dict[str, Any]:
        row = await crud.get_poster_copy_set(poster_copy_set_id)
        if not row:
            raise PosterCopySetError("POSTER_COPY_SET_NOT_FOUND", status_code=404)
        updated = await crud.update_poster_copy_set(
            poster_copy_set_id,
            status=STATUS_POSTER_COPY_REJECTED,
            reject_reason=_norm(reason),
        )
        return serialize_poster_copy_set(updated)

    @staticmethod
    async def new_version(
        poster_copy_set_id: str, request: PosterCopySetPatchRequest
    ) -> dict[str, Any]:
        """Clone an APPROVED set into a new DRAFT version; parent → SUPERSEDED."""
        row = await crud.get_poster_copy_set(poster_copy_set_id)
        if not row:
            raise PosterCopySetError("POSTER_COPY_SET_NOT_FOUND", status_code=404)
        if row.get("status") != STATUS_POSTER_COPY_APPROVED:
            raise PosterCopySetError(
                "POSTER_COPY_SET_NOT_APPROVED",
                "new-version applies to approved sets; drafts are edited in place",
                status_code=409,
            )
        merged = serialize_poster_copy_set(row)
        patch = {k: v for k, v in request.model_dump().items() if v is not None}
        merged.update(patch)
        provenance = dict(merged.get("field_provenance") or {})
        for k in patch:
            if k in ("primary_message", "support_message", "proof_points", "cta",
                     "disclaimer"):
                provenance[k] = PROVENANCE_OPERATOR
        merged["field_provenance"] = provenance
        warnings = run_poster_copy_gate(merged, strict=False)
        payload = _row_payload(merged)
        payload["status"] = STATUS_POSTER_COPY_DRAFT
        payload["version"] = int(row.get("version") or 1) + 1
        payload.pop("parent_poster_copy_set_id", None)
        # Atomic: child insert + parent supersede commit (or roll back) together.
        child = await crud.create_poster_copy_set_version(
            row["product_id"],
            poster_copy_set_id,
            STATUS_POSTER_COPY_SUPERSEDED,
            **payload,
        )
        out = serialize_poster_copy_set(child)
        out["warnings"] = warnings
        return out

    @staticmethod
    async def fork_from_historical(
        poster_copy_set_id: str, request: PosterCopySetPatchRequest
    ) -> dict[str, Any]:
        """Fork a NEW draft from a SUPERSEDED historical copy set.

        A saved poster may reference a set that was APPROVED at render time and
        later SUPERSEDED. This clones that historical copy into a fresh editable
        DRAFT WITHOUT mutating the historical record — the saved poster keeps its
        exact original copy and provenance. (Approved sets use ``new_version``;
        drafts are edited in place.)
        """
        row = await crud.get_poster_copy_set(poster_copy_set_id)
        if not row:
            raise PosterCopySetError("POSTER_COPY_SET_NOT_FOUND", status_code=404)
        if row.get("status") != STATUS_POSTER_COPY_SUPERSEDED:
            raise PosterCopySetError(
                "POSTER_COPY_SET_NOT_HISTORICAL",
                "fork-from-historical applies only to superseded versions; "
                "approved sets use new-version and drafts are edited in place",
                status_code=409,
            )
        merged = serialize_poster_copy_set(row)
        patch = {k: v for k, v in request.model_dump().items() if v is not None}
        merged.update(patch)
        provenance = dict(merged.get("field_provenance") or {})
        for k in patch:
            if k in ("primary_message", "support_message", "proof_points", "cta",
                     "disclaimer"):
                provenance[k] = PROVENANCE_OPERATOR
        merged["field_provenance"] = provenance
        warnings = run_poster_copy_gate(merged, strict=False)
        payload = _row_payload(merged)
        payload["status"] = STATUS_POSTER_COPY_DRAFT
        # Next version across the product line so it never collides with an
        # existing version number.
        existing = await crud.list_poster_copy_sets_for_product(row["product_id"])
        max_v = max(
            (int(r.get("version") or 1) for r in existing),
            default=int(row.get("version") or 1),
        )
        payload["version"] = max_v + 1
        payload.pop("parent_poster_copy_set_id", None)
        child = await crud.create_poster_copy_set_child_draft(
            row["product_id"], poster_copy_set_id, **payload
        )
        out = serialize_poster_copy_set(child)
        out["warnings"] = warnings
        return out

    @staticmethod
    async def get(poster_copy_set_id: str) -> dict[str, Any]:
        row = await crud.get_poster_copy_set(poster_copy_set_id)
        if not row:
            raise PosterCopySetError("POSTER_COPY_SET_NOT_FOUND", status_code=404)
        return serialize_poster_copy_set(row)

    @staticmethod
    async def list_for_product(product_id: str) -> list[dict[str, Any]]:
        rows = await crud.list_poster_copy_sets_for_product(_norm(product_id))
        return [serialize_poster_copy_set(r) for r in rows]
