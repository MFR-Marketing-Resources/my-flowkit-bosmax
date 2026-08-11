"""Persisted, server-owned product truth contract.

The contract is deliberately separate from prompt guidance.  A prompt can ask a
model to preserve a label; this object is the authority that proves which bytes
are allowed to reach an exact compositor.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ProductTruthLock(BaseModel):
    """Immutable visual identity contract for one catalog product.

    File paths are persisted server-side during controlled onboarding.  They are
    never accepted from an IMG generation request as an authority.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(min_length=1, max_length=32)
    product_id: str = Field(min_length=1)
    canonical_media_id: str = Field(min_length=1)
    canonical_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_width: int = Field(gt=0)
    source_height: int = Field(gt=0)
    canonical_source_path: str = Field(min_length=1)
    canonical_cutout_media_id: str = Field(min_length=1)
    canonical_cutout_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_cutout_path: str = Field(min_length=1)
    alpha_mask: dict[str, Any] = Field(min_length=1)
    anchor_point: dict[str, float]
    min_scale: float = Field(gt=0)
    max_scale: float = Field(gt=0)
    allowed_bbox: dict[str, float]
    allowed_rotation: float = Field(ge=0, le=45)
    allowed_perspective: float = Field(ge=0, le=1)
    identity_lock: bool
    geometry_lock: bool
    label_lock: bool
    logo_lock: bool
    colour_lock: bool
    scale_lock: bool
    review_status: Literal["DRAFT", "PENDING_REVIEW", "APPROVED", "REJECTED"]
    failure_state: str = ""
    provenance: dict[str, Any] = Field(default_factory=dict)


class ProductTruthLockOnboardingRequest(BaseModel):
    """Human-operated preprocessing input for a pending visual lock.

    The canonical source image is resolved from the product row on the server;
    this request may identify only the already-uploaded review media that will
    be checked as a transparent cutout.  It never carries a source path or a
    generation/provider payload.
    """

    model_config = ConfigDict(extra="forbid")

    canonical_cutout_media_id: str = Field(min_length=1, max_length=256)
    anchor_point: dict[str, float]
    min_scale: float = Field(gt=0, le=10)
    max_scale: float = Field(gt=0, le=10)
    allowed_bbox: dict[str, float]
    created_by: str = Field(min_length=1, max_length=256)
    onboarding_note: str = Field(default="", max_length=2000)


class ProductTruthLockApprovalRequest(BaseModel):
    """Explicit human confirmation required before exact output is enabled."""

    model_config = ConfigDict(extra="forbid")

    reviewed_by: str = Field(min_length=1, max_length=256)
    review_note: str = Field(min_length=1, max_length=2000)
    confirm_identity: bool = False
    confirm_label_logo: bool = False
    confirm_geometry_scale: bool = False
    # Product-isolation confirmation: the cutout is the PRODUCT ONLY — no
    # unrelated props, food, decoration, or secondary objects remain (the CHEEZY
    # GARLIC "bread retained" class of defect). Fail-closed; the human decides.
    confirm_product_isolation: bool = False
