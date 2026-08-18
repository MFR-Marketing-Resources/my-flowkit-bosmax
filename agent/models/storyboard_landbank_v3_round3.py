"""Macro Round 3 production-integration models.

These frozen models mirror the four additive Round 3 tables that bind APPROVED
V3 supply to Copy Register V2 production authority and to P6 allocation:

    materialization_link_v3            -> MaterializationLinkV3
    production_copy_supply_manifest_v3 -> ProductionCopySupplyManifestV3
    manifest_item_v3                   -> ManifestItemV3
    landbank_usage_v3                  -> LandbankUsageV3

They never introduce a parallel authority: every record points BACK to an
existing ``v3_human_approval_receipt`` and FORWARD to an existing V2 blueprint
revision + V2 approval snapshot.  Materialization is deterministic and
idempotent: the link id derives from the exact approved projection identity plus
the materializer version, so re-materializing the same approved projection can
never create a duplicate authority row.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agent.models.storyboard_landbank_v3 import (
    deterministic_digest,
    deterministic_id,
)

# The materializer version participates in every deterministic id/digest, so a
# genuine algorithm change produces a distinct link (and never silently reuses a
# stale materialization).  Bump ONLY when the deterministic mapping changes.
MATERIALIZER_VERSION = "v3-to-v2-materializer-v1"

# The reuse/diversity policy is versioned data, not a hard-coded cap.  The legacy
# arbitrary REUSE_CAP=15 is intentionally NOT inherited.
REUSE_POLICY_VERSION = "production-copy-reuse-policy-v1"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

MaterializationLinkStatus = Literal[
    "MATERIALIZED", "PRODUCTION_VALID", "SUPERSEDED", "BLOCKED"
]
ManifestStatus = Literal["DRAFT", "VALIDATED", "FROZEN", "SUPERSEDED", "BLOCKED"]
DerivationSource = Literal["DETERMINISTIC", "AI_ASSISTED", "HUMAN_EDITED"]
UsageType = Literal["RESERVED", "ALLOCATED", "CONSUMED", "RELEASED", "BLOCKED"]
UsageOutcome = Literal["OK", "FAILED", "BLOCKED", "REVALIDATION_BLOCKED"]

_LINK_TERMINAL = frozenset({"PRODUCTION_VALID", "SUPERSEDED", "BLOCKED"})
_MANIFEST_TERMINAL = frozenset({"FROZEN", "SUPERSEDED", "BLOCKED"})


# --------------------------------------------------------------------------- #
# Deterministic id / digest helpers (idempotency + immutable provenance)
# --------------------------------------------------------------------------- #
def materialization_link_id(
    *,
    product_id: str,
    projection_id: str,
    projection_revision: int,
    projection_exact_digest: str,
    materializer_version: str = MATERIALIZER_VERSION,
) -> str:
    """Deterministic id for one approved projection's materialization.

    Deliberately excludes the resulting V2 blueprint id (which is itself derived
    from the same inputs) so the SAME approved projection always resolves to the
    SAME link — this is the idempotency key.
    """

    return deterministic_id(
        "mlv3",
        {
            "materializer_version": materializer_version,
            "product_id": product_id,
            "projection_id": projection_id,
            "projection_revision": int(projection_revision),
            "projection_exact_digest": projection_exact_digest,
        },
    )


def materialization_digest(payload: dict) -> str:
    return deterministic_digest({"materialization": payload})


def manifest_item_id(
    *, manifest_id: str, manifest_revision: int, item_index: int
) -> str:
    return deterministic_id(
        "miv3",
        {
            "manifest_id": manifest_id,
            "manifest_revision": int(manifest_revision),
            "item_index": int(item_index),
        },
    )


def manifest_item_digest(payload: dict) -> str:
    return deterministic_digest({"manifest_item": payload})


def manifest_digest(header: dict, ordered_item_digests: list[str]) -> str:
    return deterministic_digest(
        {"manifest_header": header, "item_digests": list(ordered_item_digests)}
    )


def usage_event_digest(payload: dict) -> str:
    return deterministic_digest({"landbank_usage": payload})


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class MaterializationLinkV3(BaseModel):
    """Immutable binding: approved V3 projection <-> exact V2 blueprint rev."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    link_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    product_id: str = Field(min_length=1)
    master_id: str = Field(min_length=1)
    master_revision: int = Field(ge=1)
    master_exact_content_digest: str = Field(pattern=_SHA256_RE.pattern)
    projection_id: str = Field(min_length=1)
    projection_revision: int = Field(ge=1)
    projection_exact_digest: str = Field(pattern=_SHA256_RE.pattern)
    derivation_source: DerivationSource = "DETERMINISTIC"
    approval_receipt_id: str = Field(min_length=1)
    approval_receipt_digest: str = Field(pattern=_SHA256_RE.pattern)
    v2_blueprint_id: str = Field(min_length=1)
    v2_blueprint_revision: int = Field(ge=1)
    v2_approval_snapshot_id: str = Field(min_length=1)
    product_truth_snapshot_id: str = Field(min_length=1)
    product_truth_snapshot_version: int = Field(ge=1)
    product_truth_snapshot_digest: str = Field(pattern=_SHA256_RE.pattern)
    formula_id: str = Field(min_length=1)
    formula_version: str = Field(min_length=1)
    evidence_digest: str = Field(pattern=_SHA256_RE.pattern)
    target_duration_seconds: int = Field(gt=0)
    materializer_version: str = Field(min_length=1)
    materialization_digest: str = Field(pattern=_SHA256_RE.pattern)
    status: MaterializationLinkStatus = "MATERIALIZED"
    source: str = Field(min_length=1)
    supersedes_link_id: str | None = None
    supersedes_link_revision: int | None = Field(default=None, ge=1)
    created_at: str = Field(min_length=1)
    created_by: str = Field(min_length=1)

    @property
    def is_terminal(self) -> bool:
        return self.status in _LINK_TERMINAL


class ProductionCopySupplyManifestV3(BaseModel):
    """Frozen, validated production copy supply set header."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest_id: str = Field(min_length=1)
    revision: int = Field(ge=1)
    product_id: str = Field(min_length=1)
    production_plan_id: str | None = None
    campaign_key: str = ""
    recipe_policy_version: str = Field(min_length=1)
    reuse_policy_json: str = "{}"
    requested_capacity: int = Field(default=0, ge=0)
    duration_mix_json: str = "[]"
    language_profile: str = "Malay"
    source_authority_digest: str = Field(pattern=_SHA256_RE.pattern)
    item_count: int = Field(default=0, ge=0)
    valid_item_count: int = Field(default=0, ge=0)
    blocked_item_count: int = Field(default=0, ge=0)
    manifest_digest: str = Field(pattern=_SHA256_RE.pattern)
    status: ManifestStatus = "DRAFT"
    source: str = Field(min_length=1)
    supersedes_manifest_id: str | None = None
    supersedes_manifest_revision: int | None = Field(default=None, ge=1)
    created_at: str = Field(min_length=1)
    created_by: str = Field(min_length=1)
    frozen_at: str | None = None

    @property
    def is_frozen(self) -> bool:
        return self.status in _MANIFEST_TERMINAL


class ManifestItemV3(BaseModel):
    """One immutable production copy asset inside a manifest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    item_id: str = Field(min_length=1)
    manifest_id: str = Field(min_length=1)
    manifest_revision: int = Field(ge=1)
    item_index: int = Field(ge=0)
    product_id: str = Field(min_length=1)
    master_id: str = Field(min_length=1)
    master_revision: int = Field(ge=1)
    projection_id: str = Field(min_length=1)
    projection_revision: int = Field(ge=1)
    projection_exact_digest: str = Field(pattern=_SHA256_RE.pattern)
    approval_receipt_id: str = Field(min_length=1)
    materialization_link_id: str = Field(min_length=1)
    materialization_link_revision: int = Field(ge=1)
    v2_blueprint_id: str = Field(min_length=1)
    v2_blueprint_revision: int = Field(ge=1)
    v2_approval_snapshot_id: str = Field(min_length=1)
    product_truth_snapshot_digest: str = Field(pattern=_SHA256_RE.pattern)
    formula_id: str = Field(min_length=1)
    formula_version: str = Field(min_length=1)
    duration_seconds: int = Field(gt=0)
    item_digest: str = Field(pattern=_SHA256_RE.pattern)
    created_at: str = Field(min_length=1)
    created_by: str = Field(min_length=1)


class LandbankUsageV3(BaseModel):
    """Append-only production usage ledger event."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    usage_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    master_id: str | None = None
    master_revision: int | None = Field(default=None, ge=1)
    projection_id: str | None = None
    projection_revision: int | None = Field(default=None, ge=1)
    v2_blueprint_id: str = Field(min_length=1)
    v2_blueprint_revision: int = Field(ge=1)
    v2_approval_snapshot_id: str = ""
    materialization_link_id: str | None = None
    materialization_link_revision: int | None = Field(default=None, ge=1)
    manifest_id: str | None = None
    manifest_revision: int | None = Field(default=None, ge=1)
    manifest_item_id: str | None = None
    p6_plan_id: str | None = None
    p6_item_id: str | None = None
    duration_seconds: int | None = Field(default=None, gt=0)
    campaign_key: str = ""
    usage_type: UsageType
    outcome_status: UsageOutcome = "OK"
    reason_code: str = ""
    authority_digest: str = Field(pattern=_SHA256_RE.pattern)
    event_digest: str = Field(pattern=_SHA256_RE.pattern)
    created_at: str = Field(min_length=1)
    created_by: str = Field(min_length=1)
