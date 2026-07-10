"""Poster Copy Set — poster-native copywriting domain (POSTER_BUILDER_V2).

A Poster Copy Set is a first-class, persisted, explicitly-approvable POSTER
copywriting bundle. It is deliberately a SEPARATE domain from the video
`copy_set` table: poster copy is spatial and concise (one selling idea, a
first-read primary message, one support line, tight proof points, a short CTA),
NOT a compressed video script. Nothing in this module reads or writes the video
`copy_set` namespace, and poster statuses are namespaced `POSTER_COPY_*` so a
poster row can never masquerade as an approved video Copy Set.

Shared upstream truth (product row + approved product_intelligence_snapshot +
grounding) is REFERENCED, never duplicated.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

# ─── Status machine (poster namespace — distinct from video copy statuses) ───
STATUS_POSTER_COPY_DRAFT = "POSTER_COPY_DRAFT"
STATUS_POSTER_COPY_REVIEW_REQUIRED = "POSTER_COPY_REVIEW_REQUIRED"
STATUS_POSTER_COPY_APPROVED = "POSTER_COPY_APPROVED"
STATUS_POSTER_COPY_REJECTED = "POSTER_COPY_REJECTED"
STATUS_POSTER_COPY_SUPERSEDED = "POSTER_COPY_SUPERSEDED"

POSTER_COPY_SET_STATUSES = (
    STATUS_POSTER_COPY_DRAFT,
    STATUS_POSTER_COPY_REVIEW_REQUIRED,
    STATUS_POSTER_COPY_APPROVED,
    STATUS_POSTER_COPY_REJECTED,
    STATUS_POSTER_COPY_SUPERSEDED,
)

# Approval is never implicit (mirrors claim-safe / production-approval conventions).
POSTER_COPY_APPROVAL_PHRASE = "APPROVE_POSTER_COPY_SET"

# Field-provenance source tags.
PROVENANCE_AI = "AI_GENERATED"
PROVENANCE_OPERATOR = "OPERATOR_EDIT"
PROVENANCE_FALLBACK = "FALLBACK_TEMPLATE"

# ─── Poster-native length limits (SSOT for the poster copy domain) ───────────
# Poster copy must FIT the poster. These mirror the zone caps in
# agent/authority/POSTER_RECIPES.yaml (headline 48 / support 72 / chip 36 /
# CTA 24) plus a short disclaimer line.
POSTER_NATIVE_LIMITS: dict[str, int] = {
    "primary_message": 48,
    "support_message": 72,
    "proof_point": 36,
    "cta": 24,
    "disclaimer": 100,
}
MAX_PROOF_POINTS = 3


class PosterCopyFields(BaseModel):
    """The poster-native copy payload (no hook/subhook/USP video naming)."""

    model_config = ConfigDict(extra="ignore")

    objective: str = ""
    archetype: str = ""
    angle: str = ""
    primary_message: str = ""
    support_message: str = ""
    proof_points: list[str] = Field(default_factory=list)
    offer: Optional[dict[str, Any]] = None  # reserved: OfferSpec (V1 = non-price)
    cta: str = ""
    disclaimer: str = ""
    tone: str = ""
    language: str = "ms"


class PosterCopySetCreateRequest(PosterCopyFields):
    product_id: str
    campaign_id: str = ""
    variants: list[dict[str, Any]] = Field(default_factory=list)
    field_provenance: dict[str, str] = Field(default_factory=dict)
    ai_model: str = ""
    prompt_version: str = ""


class PosterCopySetPatchRequest(BaseModel):
    """Draft-only edit. Editing an APPROVED set must go through new-version."""

    model_config = ConfigDict(extra="ignore")

    objective: Optional[str] = None
    archetype: Optional[str] = None
    angle: Optional[str] = None
    primary_message: Optional[str] = None
    support_message: Optional[str] = None
    proof_points: Optional[list[str]] = None
    cta: Optional[str] = None
    disclaimer: Optional[str] = None
    tone: Optional[str] = None
    language: Optional[str] = None
    field_provenance: Optional[dict[str, str]] = None


class PosterCopySetApproveRequest(BaseModel):
    approval_phrase: str
    approved_by: str = "operator"


class PosterCopySetRejectRequest(BaseModel):
    reason: str = ""


def validate_poster_native_lengths(fields: dict[str, Any]) -> list[str]:
    """Poster-native length validation. Returns field errors (empty = OK)."""
    errors: list[str] = []

    def _chk(name: str, value: Any, limit_key: str) -> None:
        text = str(value or "").strip()
        limit = POSTER_NATIVE_LIMITS[limit_key]
        if len(text) > limit:
            errors.append(f"{name} too long for a poster: {len(text)}/{limit} chars")

    _chk("primary_message", fields.get("primary_message"), "primary_message")
    _chk("support_message", fields.get("support_message"), "support_message")
    _chk("cta", fields.get("cta"), "cta")
    _chk("disclaimer", fields.get("disclaimer"), "disclaimer")
    points = fields.get("proof_points") or []
    if len([p for p in points if str(p or "").strip()]) > MAX_PROOF_POINTS:
        errors.append(f"proof_points: max {MAX_PROOF_POINTS} allowed")
    for i, p in enumerate(points, 1):
        _chk(f"proof_point_{i}", p, "proof_point")
    return errors


def serialize_poster_copy_set(row: dict[str, Any]) -> dict[str, Any]:
    """DB row → API shape (JSON columns decoded)."""

    def _loads(v: Any, default: Any) -> Any:
        if not v:
            return default
        try:
            return json.loads(v)
        except (TypeError, ValueError):
            return default

    out = dict(row)
    out["proof_points"] = _loads(row.get("proof_points_json"), [])
    out["offer"] = _loads(row.get("offer_json"), None)
    out["variants"] = _loads(row.get("variants_json"), [])
    out["field_provenance"] = _loads(row.get("field_provenance_json"), {})
    for k in ("proof_points_json", "offer_json", "variants_json", "field_provenance_json"):
        out.pop(k, None)
    return out


def poster_fields_to_zone_fields(copy_set: dict[str, Any]) -> dict[str, str]:
    """Map a poster-native copy set onto the recipe ZONE source-field names
    (hook / subhook / usp_1..3 / cta). This is a RENDER-TIME projection only —
    the zone names are layout slot ids in POSTER_RECIPES.yaml, not video copy;
    poster storage stays poster-native."""
    points = [str(p or "").strip() for p in (copy_set.get("proof_points") or [])]
    points += ["", "", ""]
    return {
        "hook": str(copy_set.get("primary_message") or "").strip(),
        "subhook": str(copy_set.get("support_message") or "").strip(),
        "usp_1": points[0],
        "usp_2": points[1],
        "usp_3": points[2],
        "cta": str(copy_set.get("cta") or "").strip(),
    }
