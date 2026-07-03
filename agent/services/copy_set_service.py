"""Copy Set service — Copy Strategy Studio Phase 1.

Owns the Copy Set lifecycle:

    generate → (review) → approve / reject     +  patch / regenerate

Generation REUSES existing repo copy intelligence (never re-invents it):
  1. copy_landbank_service (operator-approved COPY_MASTER rows), else
  2. copy_signal_generator_service (deterministic family/route copy),
  explicit operator-supplied fields always override the resolved values.

Approval is EXPLICIT and FAILS CLOSED: an unsafe (claim/metadata) or incomplete
Copy Set can never reach COPY_APPROVED. The service never touches the Google Flow
execution lane, the prompt compiler, or any locked path — it only persists an
approvable copy object that the compiler can later consume as copy intelligence
(see agent.models.copy_set.to_compiler_copy).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from agent.db import crud
from agent.services import copy_landbank_service
from agent.services.claim_safe_rewrite_service import FORBIDDEN_PHRASES
from agent.services.copy_signal_generator_service import generate_copy_signal_response
from agent.models.copy_set import (
    APPROVAL_PHRASE,
    SOURCE_LANDBANK,
    SOURCE_SIGNAL_GENERATOR,
    STATUS_COPY_APPROVED,
    STATUS_COPY_REJECTED,
    STATUS_COPY_REVIEW_REQUIRED,
    STATUS_DRAFT_COPY,
    CopySetApproveRequest,
    CopySetGenerateRequest,
    CopySetPatchRequest,
    CopySetRejectRequest,
    compute_dedupe_key,
    normalize_usp_set,
    serialize_copy_set,
)


# ─── Errors (router maps these to HTTP responses) ───────────
class CopySetError(Exception):
    def __init__(self, code: str, status_code: int = 400, detail: Any = None):
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.detail = detail


class CopySetPermissionError(Exception):
    def __init__(self, code: str, expected: str | None = None):
        super().__init__(code)
        self.code = code
        self.expected = expected


# ─── Claim / risk guard (fail-closed vocabulary) ────────────
# Reuses claim_safe_rewrite_service.FORBIDDEN_PHRASES and adds the additional
# categories the mission requires. All matching is substring, casefolded.
_UNSAFE_CATEGORIES: dict[str, list[str]] = {
    "FORBIDDEN_PHRASE": [p.casefold() for p in FORBIDDEN_PHRASES],
    "MEDICAL_CLAIM": [
        "cure", "cures", "curing", "treat ", "treats", "treating", "treatment",
        "heal", "heals", "healing", "remedy", "therapy", "diagnos", "prescription",
        "ubat", "merawat", "rawatan", "menyembuh", "sembuhkan", "penyembuh",
    ],
    "GUARANTEED_RESULT": [
        "guarantee", "guaranteed", "100% result", "100% berkesan", "instant result",
        "permanent result", "permanently", "dijamin", "jaminan hasil", "pasti berkesan",
    ],
    "UNIVERSAL_SAFETY": [
        "completely safe", "totally safe", "no side effect", "no side effects",
        "zero side effect", "safe for everyone", "100% safe", "selamat untuk semua",
        "tiada kesan sampingan", "tanpa kesan sampingan",
    ],
    "BEFORE_AFTER_IMPLICATION": [
        "before and after", "before/after", "before & after", "sebelum dan selepas",
        "sebelum & selepas",
    ],
    "BABY_TREATMENT_IMPLICATION": [
        "treat baby", "cure baby", "baby treatment", "heal baby", "rawat bayi",
        "ubat bayi", "sembuhkan bayi",
    ],
    "CLINICAL_AUTHORITY_PROOF": [
        "clinically proven", "clinically tested", "doctor recommended",
        "dermatologist", "lab proven", "scientifically proven", "disahkan doktor",
        "disahkan pakar", "terbukti klinikal",
    ],
}

_PLACEHOLDER_TOKENS = [
    "{{", "}}", "[insert", "insert here", "lorem ipsum", "placeholder",
    "todo", "tbd", "xxx",
]

_METADATA_TOKENS = [
    "claim_safe", "copy_set", "workspace_execution", "prompt_fingerprint",
    "product_id", "```json", '"id":', "debug", "snapshot_id",
]

_REVIEW_ROUTES = {"STEALTH", "REVIEW_REQUIRED"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _copy_strings(fields: dict[str, Any]) -> list[str]:
    usp = fields.get("usp_set") or []
    return [
        fields.get("angle", ""),
        fields.get("hook", ""),
        fields.get("subhook", ""),
        *usp,
        fields.get("cta", ""),
    ]


def _haystack(fields: dict[str, Any]) -> str:
    return " ".join(_clean(s) for s in _copy_strings(fields)).casefold()


def assess_copy_completeness(fields: dict[str, Any]) -> dict[str, Any]:
    """A Copy Set needs at minimum a hook, one USP, and a CTA to be approvable."""
    missing: list[str] = []
    if not _clean(fields.get("hook")):
        missing.append("hook")
    if not [u for u in (fields.get("usp_set") or []) if _clean(u)]:
        missing.append("usp_set")
    if not _clean(fields.get("cta")):
        missing.append("cta")
    return {"complete": not missing, "missing_fields": missing}


def scan_copy_safety(fields: dict[str, Any], *, product_id: str = "") -> dict[str, Any]:
    """Fail-closed claim/risk scan over the operator-facing copy fields.
    Returns {"safe": bool, "violations": [codes], "detail": {code: matched}}."""
    hay = _haystack(fields)
    violations: list[str] = []
    detail: dict[str, str] = {}
    for code, tokens in _UNSAFE_CATEGORIES.items():
        hit = next((t for t in tokens if t and t in hay), None)
        if hit:
            violations.append(code)
            detail[code] = hit.strip()
    placeholder = next((t for t in _PLACEHOLDER_TOKENS if t in hay), None)
    if placeholder:
        violations.append("UNRESOLVED_PLACEHOLDER")
        detail["UNRESOLVED_PLACEHOLDER"] = placeholder
    leak = None
    pid = _clean(product_id).casefold()
    if pid and len(pid) >= 6 and pid in hay:
        leak = "product_id"
    if leak is None:
        leak = next((t for t in _METADATA_TOKENS if t in hay), None)
    if leak:
        violations.append("INTERNAL_METADATA_LEAK")
        detail["INTERNAL_METADATA_LEAK"] = leak
    return {"safe": not violations, "violations": violations, "detail": detail}


# ─── Copy resolution (reuse existing repo logic) ────────────
async def _resolve_base_copy(
    req: CopySetGenerateRequest, product: dict[str, Any]
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    landbank = copy_landbank_service.lookup(req.product_id, angle=req.angle)
    if landbank:
        base = {
            "angle": landbank.get("angle") or product.get("copywriting_angle") or "",
            "hook": landbank.get("hook", ""),
            "subhook": landbank.get("subhook", ""),
            "usp_set": landbank.get("usps") or [],
            "cta": landbank.get("cta", ""),
            "formula_family": landbank.get("formula_family") or "HSO",
            "route_type": req.route_type or "DIRECT",
            "platform": req.platform,
            "language": landbank.get("language") or req.language,
        }
        provenance = {"resolver": "copy_landbank_service", "copy_id": landbank.get("copy_id", "")}
        return base, SOURCE_LANDBANK, provenance

    response = await generate_copy_signal_response(
        {"product_id": req.product_id, "content_style_mode": req.content_style_mode}
    )
    signals = response.copy_signals or {}
    usps = [signals.get("usp_1"), signals.get("usp_2"), signals.get("usp_3")]
    base = {
        "angle": product.get("copywriting_angle") or "",
        "hook": signals.get("hook", ""),
        "subhook": signals.get("subhook", ""),
        "usp_set": [u for u in usps if u],
        "cta": signals.get("cta", ""),
        "formula_family": signals.get("formula") or "HSO",
        "route_type": req.route_type or response.route or "DIRECT",
        "platform": req.platform,
        "language": req.language,
    }
    provenance = {
        "resolver": "copy_signal_generator_service",
        "route": response.route,
        "review_status": response.review_status,
        "claim_gate": response.claim_gate,
        "copy_quality_status": response.copy_quality_status,
        "text_to_video_readiness_status": response.text_to_video_readiness_status,
        "warnings": list(response.warnings or []),
    }
    return base, SOURCE_SIGNAL_GENERATOR, provenance


def _apply_overrides(base: dict[str, Any], req: CopySetGenerateRequest) -> dict[str, Any]:
    fields = dict(base)
    if req.angle is not None:
        fields["angle"] = req.angle
    if req.hook is not None:
        fields["hook"] = req.hook
    if req.subhook is not None:
        fields["subhook"] = req.subhook
    explicit_usps = normalize_usp_set(req.usp_set, req.usp1, req.usp2, req.usp3)
    if explicit_usps:
        fields["usp_set"] = explicit_usps
    if req.cta is not None:
        fields["cta"] = req.cta
    if req.formula_family:
        fields["formula_family"] = req.formula_family
    if req.route_type:
        fields["route_type"] = req.route_type
    if req.platform:
        fields["platform"] = req.platform
    if req.language:
        fields["language"] = req.language
    return _normalize_fields(fields)


def _normalize_fields(fields: dict[str, Any]) -> dict[str, Any]:
    return {
        "angle": _clean(fields.get("angle")),
        "hook": _clean(fields.get("hook")),
        "subhook": _clean(fields.get("subhook")),
        "usp_set": normalize_usp_set(fields.get("usp_set")),
        "cta": _clean(fields.get("cta")),
        "formula_family": (_clean(fields.get("formula_family")).upper() or "HSO"),
        "route_type": (_clean(fields.get("route_type")).upper() or "DIRECT"),
        "platform": (_clean(fields.get("platform")).upper() or "TIKTOK"),
        "language": (_clean(fields.get("language")).upper() or "BM_MS"),
    }


def _dedupe_key_for(product_id: str, fields: dict[str, Any]) -> str:
    return compute_dedupe_key(
        product_id=product_id,
        angle=fields["angle"],
        hook=fields["hook"],
        subhook=fields["subhook"],
        usp_set=fields["usp_set"],
        cta=fields["cta"],
        platform=fields["platform"],
        language=fields["language"],
        route_type=fields["route_type"],
    )


def _status_for(fields: dict[str, Any], product_id: str) -> tuple[str, dict[str, Any]]:
    completeness = assess_copy_completeness(fields)
    safety = scan_copy_safety(fields, product_id=product_id)
    needs_review = (
        (not completeness["complete"])
        or (not safety["safe"])
        or fields["route_type"] in _REVIEW_ROUTES
    )
    status = STATUS_COPY_REVIEW_REQUIRED if needs_review else STATUS_DRAFT_COPY
    claim_review = {
        "completeness": completeness,
        "safety": safety,
        "route_type": fields["route_type"],
    }
    return status, claim_review


# ─── Public service API ─────────────────────────────────────
async def generate_copy_set(request: CopySetGenerateRequest | dict) -> dict[str, Any]:
    req = request if isinstance(request, CopySetGenerateRequest) else CopySetGenerateRequest.model_validate(request)
    product = await crud.get_product(req.product_id)
    if not product:
        raise CopySetError("PRODUCT_NOT_FOUND", status_code=404, detail={"product_id": req.product_id})

    base, source, provenance = await _resolve_base_copy(req, product)
    fields = _apply_overrides(base, req)
    dedupe_key = _dedupe_key_for(req.product_id, fields)

    existing = await crud.find_copy_set_by_dedupe_key(dedupe_key)
    if existing:
        return {
            "copy_set": serialize_copy_set(existing),
            "created": False,
            "dedupe_match": True,
        }

    status, claim_review = _status_for(fields, req.product_id)
    row = await crud.create_copy_set(
        req.product_id,
        angle=fields["angle"],
        hook=fields["hook"],
        subhook=fields["subhook"],
        usp_set_json=json.dumps(fields["usp_set"]),
        cta=fields["cta"],
        platform=fields["platform"],
        language=fields["language"],
        route_type=fields["route_type"],
        formula_family=fields["formula_family"],
        status=status,
        dedupe_key=dedupe_key,
        source=source,
        provenance_json=json.dumps(provenance),
        claim_review_json=json.dumps(claim_review),
    )
    return {"copy_set": serialize_copy_set(row), "created": True, "dedupe_match": False}


async def get_copy_set(copy_set_id: str) -> dict[str, Any] | None:
    row = await crud.get_copy_set(copy_set_id)
    return serialize_copy_set(row) if row else None


async def list_copy_sets(product_id: str) -> list[dict[str, Any]]:
    rows = await crud.list_copy_sets_for_product(product_id)
    return [serialize_copy_set(row) for row in rows]


async def patch_copy_set(copy_set_id: str, request: CopySetPatchRequest | dict) -> dict[str, Any]:
    req = request if isinstance(request, CopySetPatchRequest) else CopySetPatchRequest.model_validate(request)
    row = await crud.get_copy_set(copy_set_id)
    if not row:
        raise CopySetError("COPY_SET_NOT_FOUND", status_code=404)
    current = serialize_copy_set(row)
    fields = {
        "angle": req.angle if req.angle is not None else current["angle"],
        "hook": req.hook if req.hook is not None else current["hook"],
        "subhook": req.subhook if req.subhook is not None else current["subhook"],
        "usp_set": req.usp_set if req.usp_set is not None else current["usp_set"],
        "cta": req.cta if req.cta is not None else current["cta"],
        "formula_family": req.formula_family if req.formula_family else current["formula_family"],
        "route_type": req.route_type if req.route_type else current["route_type"],
        "platform": req.platform if req.platform else current["platform"],
        "language": req.language if req.language else current["language"],
    }
    fields = _normalize_fields(fields)
    dedupe_key = _dedupe_key_for(current["product_id"], fields)
    # Any edit drops prior approval — an approved Copy Set never survives a silent
    # content change. Re-derive status from the edited content.
    status, claim_review = _status_for(fields, current["product_id"])
    updated = await crud.update_copy_set(
        copy_set_id,
        angle=fields["angle"],
        hook=fields["hook"],
        subhook=fields["subhook"],
        usp_set_json=json.dumps(fields["usp_set"]),
        cta=fields["cta"],
        platform=fields["platform"],
        language=fields["language"],
        route_type=fields["route_type"],
        formula_family=fields["formula_family"],
        dedupe_key=dedupe_key,
        status=status,
        claim_review_json=json.dumps(claim_review),
        reviewer_note=req.reviewer_note if req.reviewer_note is not None else row.get("reviewer_note"),
        approved_at=None,
        approved_by=None,
    )
    return serialize_copy_set(updated)


async def approve_copy_set(copy_set_id: str, request: CopySetApproveRequest | dict) -> dict[str, Any]:
    req = request if isinstance(request, CopySetApproveRequest) else CopySetApproveRequest.model_validate(request)
    if req.approval_phrase != APPROVAL_PHRASE:
        raise CopySetPermissionError("INVALID_APPROVAL_PHRASE", expected=APPROVAL_PHRASE)
    row = await crud.get_copy_set(copy_set_id)
    if not row:
        raise CopySetError("COPY_SET_NOT_FOUND", status_code=404)
    fields = serialize_copy_set(row)

    completeness = assess_copy_completeness(fields)
    if not completeness["complete"]:
        raise CopySetError("COPY_SET_INCOMPLETE", status_code=422, detail=completeness)
    safety = scan_copy_safety(fields, product_id=row["product_id"])
    if not safety["safe"]:
        raise CopySetError("COPY_SET_UNSAFE", status_code=422, detail=safety)

    claim_review = {
        "completeness": completeness,
        "safety": safety,
        "route_type": fields["route_type"],
        "approved": True,
    }
    updated = await crud.update_copy_set(
        copy_set_id,
        status=STATUS_COPY_APPROVED,
        approved_at=_now(),
        approved_by=_clean(req.approved_by) or "operator",
        reviewer_note=req.reviewer_note if req.reviewer_note is not None else row.get("reviewer_note"),
        claim_review_json=json.dumps(claim_review),
    )
    return serialize_copy_set(updated)


async def reject_copy_set(copy_set_id: str, request: CopySetRejectRequest | dict) -> dict[str, Any]:
    req = request if isinstance(request, CopySetRejectRequest) else CopySetRejectRequest.model_validate(request)
    row = await crud.get_copy_set(copy_set_id)
    if not row:
        raise CopySetError("COPY_SET_NOT_FOUND", status_code=404)
    updated = await crud.update_copy_set(
        copy_set_id,
        status=STATUS_COPY_REJECTED,
        reviewer_note=req.reviewer_note,
        approved_at=None,
        approved_by=None,
    )
    return serialize_copy_set(updated)


async def regenerate_copy_set(
    copy_set_id: str, request: CopySetGenerateRequest | dict | None = None
) -> dict[str, Any]:
    """Regenerate copy for an existing Copy Set IN PLACE (stable id, resets any
    prior approval). Reuses the same resolver chain as generate."""
    row = await crud.get_copy_set(copy_set_id)
    if not row:
        raise CopySetError("COPY_SET_NOT_FOUND", status_code=404)
    product = await crud.get_product(row["product_id"])
    if not product:
        raise CopySetError("PRODUCT_NOT_FOUND", status_code=404, detail={"product_id": row["product_id"]})

    overrides = request if isinstance(request, CopySetGenerateRequest) else (
        CopySetGenerateRequest.model_validate({**request, "product_id": row["product_id"]})
        if isinstance(request, dict)
        else None
    )
    gen_req = overrides or CopySetGenerateRequest(
        product_id=row["product_id"],
        platform=row["platform"],
        language=row["language"],
    )
    if not gen_req.product_id:
        gen_req.product_id = row["product_id"]

    base, source, provenance = await _resolve_base_copy(gen_req, product)
    fields = _apply_overrides(base, gen_req)
    dedupe_key = _dedupe_key_for(row["product_id"], fields)
    status, claim_review = _status_for(fields, row["product_id"])
    provenance = {**provenance, "regenerated_from": copy_set_id}
    updated = await crud.update_copy_set(
        copy_set_id,
        angle=fields["angle"],
        hook=fields["hook"],
        subhook=fields["subhook"],
        usp_set_json=json.dumps(fields["usp_set"]),
        cta=fields["cta"],
        platform=fields["platform"],
        language=fields["language"],
        route_type=fields["route_type"],
        formula_family=fields["formula_family"],
        dedupe_key=dedupe_key,
        status=status,
        source=source,
        provenance_json=json.dumps(provenance),
        claim_review_json=json.dumps(claim_review),
        approved_at=None,
        approved_by=None,
    )
    return serialize_copy_set(updated)
