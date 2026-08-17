"""Macro Round 3 P4 — Production Copy Supply Manifest.

A manifest is a FROZEN, validated set of production copy assets for one product /
plan / campaign.  It is NOT a new copy authority: every item points to exactly one
V2 PRODUCTION_VALID blueprint (via its materialization link) which itself points
back to an approved V3 projection + human approval receipt.

Build validates every candidate against CURRENT authority; freeze re-validates and
makes the header + item set immutable.  Changed supply produces a NEW revision,
never a mutation of a frozen manifest.  The reuse policy is versioned data (the
legacy arbitrary REUSE_CAP=15 is intentionally NOT inherited).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from agent.authority.copy_blueprint_v2_authority import formula_version as v2_formula_version
from agent.models.storyboard_landbank_v3 import deterministic_digest, deterministic_id
from agent.models.storyboard_landbank_v3_round3 import (
    REUSE_POLICY_VERSION,
    ManifestItemV3,
    MaterializationLinkV3,
    ProductionCopySupplyManifestV3,
    manifest_digest as compute_manifest_digest,
    manifest_item_digest as compute_item_digest,
    manifest_item_id,
)
from agent.services import copy_register_v2_service as v2svc
from agent.services import production_copy_supply_service as supply_status
from agent.services import production_supply_repository as supply_repo

# Default owner reuse policy: within ONE plan the exact same duration projection
# is NOT reused unless controlled reuse is explicitly enabled.  Cross-plan reuse
# is governed by recipe/policy.  Semantic fatigue is advisory, never a hard gate.
DEFAULT_REUSE_POLICY: dict[str, Any] = {
    "policy_version": REUSE_POLICY_VERSION,
    "exact_reuse_within_plan": False,
    "cross_plan_reuse": "BY_RECIPE_POLICY",
    "semantic_fatigue_advisory": True,
}


class ManifestError(Exception):
    def __init__(
        self,
        code: str,
        detail: str,
        *,
        status_code: int = 409,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code
        self.details = details or {}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def _validate_link(
    link: MaterializationLinkV3, current_truth: dict[str, Any] | None
) -> tuple[bool, str | None]:
    """A link is production-valid iff its V2 blueprint is PRODUCTION_VALID and its
    bound authority still matches CURRENT Product Truth + formula authority."""

    try:
        blueprint = await v2svc.get_blueprint(
            link.v2_blueprint_id, link.v2_blueprint_revision
        )
    except v2svc.CopyRegisterV2Error:
        return False, "V2_BLUEPRINT_MISSING"
    if blueprint.status != "PRODUCTION_VALID":
        return False, f"BLUEPRINT_{blueprint.status}"
    if link.status != "PRODUCTION_VALID":
        return False, f"LINK_{link.status}"
    if current_truth is None:
        return False, "PRODUCT_TRUTH_UNAVAILABLE"
    if (
        link.product_truth_snapshot_version != current_truth["version"]
        or link.product_truth_snapshot_digest != current_truth["digest"]
    ):
        return False, "PRODUCT_TRUTH_ADVANCED"
    if link.formula_version != v2_formula_version(link.formula_id):
        return False, "FORMULA_VERSION_ADVANCED"
    return True, None


def _item_payload(link: MaterializationLinkV3) -> dict[str, Any]:
    return {
        "product_id": link.product_id,
        "master": [link.master_id, link.master_revision],
        "projection": [link.projection_id, link.projection_revision, link.projection_exact_digest],
        "approval_receipt_id": link.approval_receipt_id,
        "materialization_link": [link.link_id, link.revision],
        "v2_blueprint": [link.v2_blueprint_id, link.v2_blueprint_revision, link.v2_approval_snapshot_id],
        "formula": [link.formula_id, link.formula_version],
        "duration_seconds": link.target_duration_seconds,
        "product_truth_snapshot_digest": link.product_truth_snapshot_digest,
    }


async def build_manifest(
    product_id: str,
    *,
    requested_capacity: int,
    actor_id: str,
    duration_seconds: int | None = None,
    reuse_policy: dict[str, Any] | None = None,
    campaign_key: str = "",
    production_plan_id: str | None = None,
    recipe_policy_version: str = REUSE_POLICY_VERSION,
    language_profile: str = "Malay",
    source: str = "v3-round3-manifest",
) -> dict[str, Any]:
    """Build a DRAFT manifest from the product's MATERIALIZED supply.

    Only V2 PRODUCTION_VALID + current-authority items are included.  Stale/blocked
    candidates are reported (never silently dropped) so an operator can repair.
    """

    if requested_capacity < 1:
        raise ManifestError(
            "MANIFEST_CAPACITY_INVALID",
            "requested_capacity must be >= 1.",
            status_code=422,
        )
    policy = {**DEFAULT_REUSE_POLICY, **(reuse_policy or {})}
    allow_exact_reuse = bool(policy.get("exact_reuse_within_plan"))

    current_truth = await supply_status._current_truth(product_id)
    links = await supply_repo.list_links_for_product(product_id, limit=4096)

    eligible: list[MaterializationLinkV3] = []
    blocked: list[dict[str, Any]] = []
    seen_projection_digests: set[str] = set()
    for link in links:
        if duration_seconds is not None and link.target_duration_seconds != int(duration_seconds):
            continue
        ok, reason = await _validate_link(link, current_truth)
        if not ok:
            blocked.append(
                {
                    "projection_id": link.projection_id,
                    "v2_blueprint_id": link.v2_blueprint_id,
                    "reason": reason,
                }
            )
            continue
        if not allow_exact_reuse and link.projection_exact_digest in seen_projection_digests:
            blocked.append(
                {
                    "projection_id": link.projection_id,
                    "v2_blueprint_id": link.v2_blueprint_id,
                    "reason": "EXACT_REUSE_BLOCKED_BY_POLICY",
                }
            )
            continue
        seen_projection_digests.add(link.projection_exact_digest)
        eligible.append(link)

    # Deterministic selection order (duration, projection id) so the same supply +
    # policy + seed selects the same items every time.
    eligible.sort(key=lambda link: (link.target_duration_seconds, link.projection_id))
    selected = eligible[: int(requested_capacity)]

    manifest_id = deterministic_id(
        "mfstv3",
        {
            "product_id": product_id,
            "campaign_key": campaign_key,
            "production_plan_id": production_plan_id or "",
            "recipe_policy_version": recipe_policy_version,
        },
    )
    revision = await supply_repo.next_manifest_revision(manifest_id)
    created_at = _now()

    items: list[ManifestItemV3] = []
    for index, link in enumerate(selected):
        payload = _item_payload(link)
        items.append(
            ManifestItemV3(
                item_id=manifest_item_id(
                    manifest_id=manifest_id, manifest_revision=revision, item_index=index
                ),
                manifest_id=manifest_id,
                manifest_revision=revision,
                item_index=index,
                product_id=link.product_id,
                master_id=link.master_id,
                master_revision=link.master_revision,
                projection_id=link.projection_id,
                projection_revision=link.projection_revision,
                projection_exact_digest=link.projection_exact_digest,
                approval_receipt_id=link.approval_receipt_id,
                materialization_link_id=link.link_id,
                materialization_link_revision=link.revision,
                v2_blueprint_id=link.v2_blueprint_id,
                v2_blueprint_revision=link.v2_blueprint_revision,
                v2_approval_snapshot_id=link.v2_approval_snapshot_id,
                product_truth_snapshot_digest=link.product_truth_snapshot_digest,
                formula_id=link.formula_id,
                formula_version=link.formula_version,
                duration_seconds=link.target_duration_seconds,
                item_digest=compute_item_digest(payload),
                created_at=created_at,
                created_by=actor_id,
            )
        )

    source_authority_digest = deterministic_digest(
        {
            "authority_set": sorted(
                [
                    item.v2_blueprint_id
                    + ":"
                    + str(item.v2_blueprint_revision)
                    + ":"
                    + item.v2_approval_snapshot_id
                    + ":"
                    + item.projection_exact_digest
                    for item in items
                ]
            )
        }
    )
    header = {
        "manifest_id": manifest_id,
        "revision": revision,
        "product_id": product_id,
        "production_plan_id": production_plan_id or "",
        "campaign_key": campaign_key,
        "recipe_policy_version": recipe_policy_version,
        "requested_capacity": int(requested_capacity),
        "duration_seconds": duration_seconds,
        "language_profile": language_profile,
        "reuse_policy": policy,
        "source_authority_digest": source_authority_digest,
    }
    manifest = ProductionCopySupplyManifestV3(
        manifest_id=manifest_id,
        revision=revision,
        product_id=product_id,
        production_plan_id=production_plan_id,
        campaign_key=campaign_key,
        recipe_policy_version=recipe_policy_version,
        reuse_policy_json=json.dumps(policy, sort_keys=True),
        requested_capacity=int(requested_capacity),
        duration_mix_json=json.dumps(
            [int(duration_seconds)] if duration_seconds is not None else []
        ),
        language_profile=language_profile,
        source_authority_digest=source_authority_digest,
        item_count=len(items),
        valid_item_count=len(items),
        blocked_item_count=len(blocked),
        manifest_digest=compute_manifest_digest(header, [item.item_digest for item in items]),
        status="DRAFT",
        source=source,
        created_at=created_at,
        created_by=actor_id,
    )
    await supply_repo.insert_manifest_with_items(manifest, items)

    return {
        "manifest": manifest,
        "items": items,
        "requested_capacity": int(requested_capacity),
        "selected_count": len(items),
        "valid_count": len(items),
        "blocked_count": len(blocked),
        "blocked": blocked,
        "shortfall": max(0, int(requested_capacity) - len(items)),
        "reuse_policy": policy,
    }


async def freeze_manifest(
    manifest_id: str, revision: int, *, actor_id: str
) -> dict[str, Any]:
    """Re-validate every item against CURRENT authority, then FREEZE (immutable).

    If any item is no longer production-valid the freeze is refused and the stale
    items are returned so an operator can rebuild — the frozen manifest can never
    contain a stale asset.
    """

    manifest = await supply_repo.get_manifest(manifest_id, revision)
    if manifest is None:
        raise ManifestError(
            "MANIFEST_NOT_FOUND", f"Manifest {manifest_id}:{revision} not found.", status_code=404
        )
    if manifest.status in {"FROZEN", "SUPERSEDED", "BLOCKED"}:
        # Already terminal: freeze is idempotent for a FROZEN manifest.
        return {"manifest": manifest, "already_frozen": manifest.status == "FROZEN"}

    items = await supply_repo.list_manifest_items(manifest_id, revision)
    if not items:
        raise ManifestError(
            "MANIFEST_EMPTY", "Cannot freeze a manifest with no valid items.", status_code=422
        )
    current_truth = await supply_status._current_truth(manifest.product_id)
    stale: list[dict[str, Any]] = []
    for item in items:
        link = await supply_repo.get_materialization_link(
            item.materialization_link_id, item.materialization_link_revision
        )
        if link is None:
            stale.append({"item_id": item.item_id, "reason": "LINK_MISSING"})
            continue
        ok, reason = await _validate_link(link, current_truth)
        if not ok:
            stale.append({"item_id": item.item_id, "reason": reason})

    if stale:
        raise ManifestError(
            "MANIFEST_ITEM_STALE",
            "One or more manifest items are no longer production-valid; rebuild before freezing.",
            details={"stale": stale},
        )

    await supply_repo.set_manifest_frozen(manifest_id, revision, frozen_at=_now())
    frozen = await supply_repo.get_manifest(manifest_id, revision)
    return {"manifest": frozen, "already_frozen": False, "item_count": len(items)}


async def get_manifest_view(
    manifest_id: str, revision: int | None = None
) -> dict[str, Any]:
    manifest = await supply_repo.get_manifest(manifest_id, revision)
    if manifest is None:
        raise ManifestError(
            "MANIFEST_NOT_FOUND", f"Manifest {manifest_id} not found.", status_code=404
        )
    items = await supply_repo.list_manifest_items(manifest.manifest_id, manifest.revision)
    return {"manifest": manifest, "items": items}
