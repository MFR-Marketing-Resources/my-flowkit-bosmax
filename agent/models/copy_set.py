"""Copy Set models — Copy Strategy Studio Phase 1.

A Copy Set is a first-class, persisted, explicitly-approvable copywriting bundle
for a product (angle / hook / subhook / usp set / cta + platform / language /
route). It is the pre-generation copywriting object that later feeds the canonical
prompt compiler as copy intelligence. This module holds the API/data models,
the status constants, the dedupe key, and the compiler-compat adapter — no DB or
service logic lives here.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


# ─── Status machine ─────────────────────────────────────────
STATUS_DRAFT_COPY = "DRAFT_COPY"
STATUS_COPY_REVIEW_REQUIRED = "COPY_REVIEW_REQUIRED"
STATUS_COPY_APPROVED = "COPY_APPROVED"
STATUS_COPY_REJECTED = "COPY_REJECTED"

COPY_SET_STATUSES = (
    STATUS_DRAFT_COPY,
    STATUS_COPY_REVIEW_REQUIRED,
    STATUS_COPY_APPROVED,
    STATUS_COPY_REJECTED,
)

# Explicit approval phrase (mirrors claim_safe_rewrite_service / production
# prompt approval conventions: approval is never implicit).
APPROVAL_PHRASE = "APPROVE_COPY_SET"

# Copy source provenance tags.
SOURCE_LANDBANK = "COPY_LANDBANK"
SOURCE_SIGNAL_GENERATOR = "COPY_SIGNAL_GENERATOR"
SOURCE_OPERATOR = "OPERATOR_EXPLICIT"
SOURCE_AI_COPY_ASSIST = "AI_COPY_ASSIST"


# ─── Request / response models ──────────────────────────────
class CopySetGenerateRequest(BaseModel):
    """Generate (or resolve) a Copy Set draft for a product. Any explicit field
    supplied here overrides the generated/landbank value for that field."""

    model_config = ConfigDict(extra="allow")

    product_id: str
    angle: Optional[str] = None
    hook: Optional[str] = None
    subhook: Optional[str] = None
    usp_set: Optional[list[str]] = None
    usp1: Optional[str] = None
    usp2: Optional[str] = None
    usp3: Optional[str] = None
    cta: Optional[str] = None
    platform: str = "TIKTOK"
    language: str = "BM_MS"
    route_type: Optional[str] = None
    formula_family: Optional[str] = None
    content_style_mode: str = "UGC_IPHONE"


class AICopyAssistRequest(BaseModel):
    """AI Copy Assist — generate reviewable candidate Copy Set(s) for a product.
    Optional fields steer the brief; explicit fields also override AI output for
    that field. Candidates are NEVER auto-approved (see ai_copy_assist_service)."""

    model_config = ConfigDict(extra="allow")

    product_id: str
    angle: Optional[str] = None
    hook: Optional[str] = None
    subhook: Optional[str] = None
    usp_set: Optional[list[str]] = None
    cta: Optional[str] = None
    platform: str = "TIKTOK"
    language: str = "BM_MS"
    route_type: Optional[str] = None
    formula_family: Optional[str] = None
    content_style_mode: str = "UGC_IPHONE"
    operator_notes: Optional[str] = None
    candidate_count: int = Field(default=1, ge=1, le=3)
    # Operator override: generate even when the product has NO approved
    # product-intelligence snapshot (degraded, non-factual copy). Default fails
    # closed so ungrounded products are blocked, not silently guessed in the dark.
    allow_ungrounded: bool = False


class AICopyAssistBatchRequest(BaseModel):
    """AI Copy Assist Batch — generate multiple reviewable candidate Copy Sets
    in a single request. Produces requested_count candidates (default 5, range
    3-10), each independently deduped, safety-scanned, and similarity-scored.
    A copy_generation_batch ledger row is created for audit.

    Optional ``dry_run`` validates request and product context only. It does
    NOT call the provider and does NOT persist Copy Set or ledger rows."""

    model_config = ConfigDict(extra="allow")

    product_id: str
    requested_count: int = Field(default=5, ge=3, le=10)
    platform: str = "TIKTOK"
    language: str = "BM_MS"
    angle: Optional[str] = None
    hook: Optional[str] = None
    route_type: Optional[str] = None
    formula_family: Optional[str] = None
    content_style_mode: str = "UGC_IPHONE"
    operator_notes: Optional[str] = None
    dedupe_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    provider_lane: Optional[str] = None
    provider_model: Optional[str] = None
    dry_run: bool = False
    # Operator override to generate on an ungrounded product (see AICopyAssistRequest).
    allow_ungrounded: bool = False


class CopySetPatchRequest(BaseModel):
    """Operator edit of a draft/review Copy Set. Editing an approved Copy Set
    reverts it to DRAFT_COPY (re-review) — approval never survives a silent edit."""

    model_config = ConfigDict(extra="forbid")

    angle: Optional[str] = None
    hook: Optional[str] = None
    subhook: Optional[str] = None
    usp_set: Optional[list[str]] = None
    cta: Optional[str] = None
    platform: Optional[str] = None
    language: Optional[str] = None
    route_type: Optional[str] = None
    formula_family: Optional[str] = None
    reviewer_note: Optional[str] = None


class CopySetRegenerateRequest(BaseModel):
    """Optional overrides when regenerating an existing Copy Set in place. The
    product is taken from the existing Copy Set, so product_id is not required."""

    model_config = ConfigDict(extra="forbid")

    angle: Optional[str] = None
    platform: Optional[str] = None
    language: Optional[str] = None
    route_type: Optional[str] = None
    formula_family: Optional[str] = None
    content_style_mode: Optional[str] = None


class CopySetApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_phrase: str
    reviewer_note: Optional[str] = None
    approved_by: Optional[str] = None


class CopySetRejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewer_note: str


class CopySetResponse(BaseModel):
    copy_set_id: str
    product_id: str
    angle: str = ""
    hook: str = ""
    subhook: str = ""
    usp_set: list[str] = Field(default_factory=list)
    cta: str = ""
    platform: str = "TIKTOK"
    language: str = "BM_MS"
    route_type: str = "DIRECT"
    formula_family: str = "HSO"
    status: str = STATUS_DRAFT_COPY
    dedupe_key: str = ""
    source: str = ""
    provenance: dict[str, Any] = Field(default_factory=dict)
    claim_review: dict[str, Any] = Field(default_factory=dict)
    reviewer_note: Optional[str] = None
    approved_at: Optional[str] = None
    approved_by: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ─── Helpers ────────────────────────────────────────────────
def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def normalize_usp_set(*candidates: Any) -> list[str]:
    """Flatten usp inputs (a list, or usp1/usp2/usp3 scalars) into a clean,
    de-duplicated, order-preserving list of non-empty strings."""
    flat: list[Any] = []
    for candidate in candidates:
        if candidate is None:
            continue
        if isinstance(candidate, (list, tuple)):
            flat.extend(candidate)
        else:
            flat.append(candidate)
    out: list[str] = []
    seen: set[str] = set()
    for item in flat:
        text = _clean(item)
        if text and text.casefold() not in seen:
            seen.add(text.casefold())
            out.append(text)
    return out


def compute_dedupe_key(
    *,
    product_id: str,
    angle: str,
    hook: str,
    subhook: str,
    usp_set: list[str],
    cta: str,
    platform: str,
    language: str,
    route_type: str,
) -> str:
    """Stable logical identity for a Copy Set. Two requests that resolve to the
    same product + angle + hook + subhook + usp set + cta + platform + language +
    route_type collapse to the same key so we never persist blind duplicates."""
    parts = [
        _clean(product_id).casefold(),
        _clean(angle).casefold(),
        _clean(hook).casefold(),
        _clean(subhook).casefold(),
        "|".join(_clean(u).casefold() for u in usp_set),
        _clean(cta).casefold(),
        _clean(platform).casefold(),
        _clean(language).casefold(),
        _clean(route_type).casefold(),
    ]
    return "␟".join(parts)


def to_compiler_copy(copy_set: dict[str, Any]) -> dict[str, Any]:
    """Adapt a Copy Set (DB row or serialized response) into the exact `copy`
    dict shape consumed by canonical_prompt_compiler.normalize_copy_intelligence.
    Only clean copy fields cross this boundary — never status, ids, provenance,
    dedupe keys, or any other internal metadata."""
    usp_set = copy_set.get("usp_set")
    if usp_set is None:
        usp_set = _load_json_list(copy_set.get("usp_set_json"))
    return {
        "angle": _clean(copy_set.get("angle")),
        "copywriting_angle": _clean(copy_set.get("angle")),
        "hook": _clean(copy_set.get("hook")),
        "subhook": _clean(copy_set.get("subhook")),
        "usps": [ _clean(u) for u in (usp_set or []) if _clean(u) ],
        "cta": _clean(copy_set.get("cta")),
        "formula_family": _clean(copy_set.get("formula_family")) or "HSO",
    }


def _load_json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return [str(v) for v in parsed] if isinstance(parsed, list) else []


def _load_json_obj(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def serialize_copy_set(row: dict[str, Any]) -> dict[str, Any]:
    """Turn a raw copy_set DB row into an API-facing dict (JSON columns parsed)."""
    return {
        "copy_set_id": row.get("copy_set_id"),
        "product_id": row.get("product_id"),
        "angle": row.get("angle") or "",
        "hook": row.get("hook") or "",
        "subhook": row.get("subhook") or "",
        "usp_set": _load_json_list(row.get("usp_set_json")),
        "cta": row.get("cta") or "",
        "platform": row.get("platform") or "TIKTOK",
        "language": row.get("language") or "BM_MS",
        "route_type": row.get("route_type") or "DIRECT",
        "formula_family": row.get("formula_family") or "HSO",
        "status": row.get("status") or STATUS_DRAFT_COPY,
        "dedupe_key": row.get("dedupe_key") or "",
        "source": row.get("source") or "",
        "provenance": _load_json_obj(row.get("provenance_json")),
        "claim_review": _load_json_obj(row.get("claim_review_json")),
        "reviewer_note": row.get("reviewer_note"),
        "approved_at": row.get("approved_at"),
        "approved_by": row.get("approved_by"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        # Phase 1 fields (Copy Intelligence foundation)
        "usage_count": row.get("usage_count") or 0,
        "last_used_at": row.get("last_used_at"),
        "used_in_modes": _load_json_list(row.get("used_in_modes")),
        "uniqueness_score": row.get("uniqueness_score"),
        "similar_to_copy_set_id": row.get("similar_to_copy_set_id"),
        "similarity_score": row.get("similarity_score"),
        "archived": row.get("archived") or 0,
    }
