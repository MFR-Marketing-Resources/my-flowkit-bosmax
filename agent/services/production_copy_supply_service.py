"""Macro Round 3 P3 — Approved Landbank materialization status + actions.

Read-only status enrichment (NOT_MATERIALIZED / MATERIALIZED / STALE / BLOCKED)
for the Approved Storyboard Landbank, plus explicit, human-triggered materialize
actions (single + bounded bulk).  Opening the landbank NEVER materializes; it only
reports status.  Materialization NEVER auto-approves — the human approval is the
V3 receipt, carried forward through the existing V2 gate by the materializer.
"""

from __future__ import annotations

from typing import Any

from agent.authority.copy_blueprint_v2_authority import formula_version as v2_formula_version
from agent.db.schema import get_db
from agent.models.storyboard_landbank_v3_round3 import materialization_link_id
from agent.services import copy_register_v2_service as v2svc
from agent.services import production_supply_repository as supply_repo
from agent.services.storyboard_landbank_v3_materializer import (
    MaterializationError,
    V3ToV2Materializer,
)

MAX_BULK_MATERIALIZE = 25

NOT_MATERIALIZED = "NOT_MATERIALIZED"
MATERIALIZED = "MATERIALIZED"
STALE = "STALE"
BLOCKED = "BLOCKED"
PARTIALLY_MATERIALIZED = "PARTIALLY_MATERIALIZED"


async def _current_truth(product_id: str) -> dict[str, Any] | None:
    product, snapshot = await v2svc._product_truth_rows(product_id)
    if product is None or snapshot is None:
        return None
    # Respect the V2 production truth gate: a snapshot that regressed to
    # non-APPROVED / incomplete / claim-blocked yields NO current truth, so status
    # reads report STALE (never MATERIALIZED) and capacity/build/allocate fail closed.
    if v2svc._truth_gate(product, snapshot):
        return None
    return {
        "snapshot_id": str(snapshot["snapshot_id"]),
        "version": int(snapshot["version"]),
        "digest": v2svc._truth_digest(snapshot),
    }


async def resolve_projection_materialization(
    product_id: str,
    projection: dict[str, Any],
    *,
    current_truth: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Truthful, read-only materialization status for one approved projection."""

    projection_id = projection.get("projection_id")
    projection_digest = projection.get("exact_projection_digest")
    if not projection_id or not projection_digest:
        return {"status": NOT_MATERIALIZED, "link_id": None}

    link_id = materialization_link_id(
        product_id=product_id,
        projection_id=projection_id,
        projection_revision=int(projection.get("revision") or 1),
        projection_exact_digest=projection_digest,
    )
    link = await supply_repo.get_materialization_link(link_id)
    if link is None:
        return {"status": NOT_MATERIALIZED, "link_id": None}

    base = {
        "link_id": link.link_id,
        "v2_blueprint_id": link.v2_blueprint_id,
        "v2_blueprint_revision": link.v2_blueprint_revision,
        "v2_approval_snapshot_id": link.v2_approval_snapshot_id,
        "materialization_digest": link.materialization_digest,
    }
    try:
        blueprint = await v2svc.get_blueprint(
            link.v2_blueprint_id, link.v2_blueprint_revision
        )
    except v2svc.CopyRegisterV2Error:
        return {**base, "status": BLOCKED, "reason": "V2_BLUEPRINT_MISSING"}

    if link.status == "BLOCKED" or blueprint.status in {"BLOCKED", "SUPERSEDED"}:
        return {**base, "status": BLOCKED, "reason": f"BLUEPRINT_{blueprint.status}"}
    if blueprint.status != "PRODUCTION_VALID":
        return {**base, "status": BLOCKED, "reason": "BLUEPRINT_NOT_PRODUCTION_VALID"}

    if current_truth is None:
        current_truth = await _current_truth(product_id)

    reasons: list[str] = []
    if current_truth is None:
        reasons.append("PRODUCT_TRUTH_UNAVAILABLE")
    elif (
        link.product_truth_snapshot_version != current_truth["version"]
        or link.product_truth_snapshot_digest != current_truth["digest"]
    ):
        reasons.append("PRODUCT_TRUTH_ADVANCED")
    if link.formula_version != v2_formula_version(link.formula_id):
        reasons.append("FORMULA_VERSION_ADVANCED")

    if reasons:
        return {**base, "status": STALE, "reason": ", ".join(reasons)}
    return {**base, "status": MATERIALIZED}


def _rollup(statuses: list[str]) -> str:
    if not statuses:
        return NOT_MATERIALIZED
    if all(status == MATERIALIZED for status in statuses):
        return MATERIALIZED
    if any(status == MATERIALIZED for status in statuses):
        return PARTIALLY_MATERIALIZED
    if any(status == STALE for status in statuses):
        return STALE
    if any(status == BLOCKED for status in statuses):
        return BLOCKED
    return NOT_MATERIALIZED


async def enrich_landbank_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Replace the Round 2 NOT_IN_ROUND2 stubs with truthful production status.

    Read-only: computes status per projection + an item rollup.  Never materializes.
    """

    items = payload.get("items") or []
    truth_cache: dict[str, dict[str, Any] | None] = {}
    for item in items:
        master = item.get("master") or {}
        product_id = master.get("product_id")
        if product_id and product_id not in truth_cache:
            truth_cache[product_id] = await _current_truth(product_id)
        current = truth_cache.get(product_id)

        statuses: list[str] = []
        for projection in item.get("projections") or []:
            state = await resolve_projection_materialization(
                product_id, projection, current_truth=current
            )
            projection["materialization"] = state
            statuses.append(state["status"])

        item["v2_materialization"] = _rollup(statuses)
        # Real P6 allocation status is wired in P5 (landbank_usage_v3); until an
        # item is allocated it is simply not allocated.
        item["p6_status"] = "NOT_ALLOCATED"
    return payload


async def materialize(
    *,
    projection_id: str,
    receipt_id: str,
    projection_revision: int | None = None,
    actor_id: str = "landbank-operator",
) -> dict[str, Any]:
    """Explicitly materialize one approved projection to a V2 PRODUCTION_VALID blueprint."""

    result = await V3ToV2Materializer().materialize_projection(
        projection_id=projection_id,
        receipt_id=receipt_id,
        projection_revision=projection_revision,
        actor_id=actor_id,
        source="v3-round3-landbank-materialize",
    )
    return {
        "projection_id": projection_id,
        "status": MATERIALIZED,
        "blueprint_status": result["status"],
        "blueprint_id": result["blueprint_id"],
        "revision": result["revision"],
        "link_id": result["link_id"],
        "v2_approval_snapshot_id": result["v2_approval_snapshot_id"],
        "materialization_digest": result["materialization_digest"],
        "idempotent_reuse": result["idempotent_reuse"],
    }


async def materialize_bulk(
    requests: list[dict[str, Any]], *, actor_id: str = "landbank-operator"
) -> dict[str, Any]:
    """Bounded bulk materialization of clean approved projections.

    Bounded (never unbounded fan-out); each item independent — one blocked item
    never poisons the valid ones (partial-success with explicit reason codes).
    """

    if len(requests) > MAX_BULK_MATERIALIZE:
        raise MaterializationError(
            "MATERIALIZATION_BULK_LIMIT_EXCEEDED",
            f"Bulk materialization is bounded to {MAX_BULK_MATERIALIZE} items per call.",
            status_code=422,
            details={"requested": len(requests), "limit": MAX_BULK_MATERIALIZE},
        )
    materialized: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for request in requests:
        projection_id = request.get("projection_id")
        receipt_id = request.get("receipt_id")
        try:
            materialized.append(
                await materialize(
                    projection_id=str(projection_id),
                    receipt_id=str(receipt_id),
                    projection_revision=request.get("projection_revision"),
                    actor_id=actor_id,
                )
            )
        except MaterializationError as exc:
            blocked.append(
                {
                    "projection_id": projection_id,
                    "code": exc.code,
                    "detail": exc.detail,
                    "details": exc.details,
                }
            )
    return {
        "requested": len(requests),
        "materialized_count": len(materialized),
        "blocked_count": len(blocked),
        "materialized": materialized,
        "blocked": blocked,
    }


async def _link_is_executable(link, current_truth) -> bool:
    """A materialization link is EXECUTABLE iff its V2 blueprint is still
    PRODUCTION_VALID and bound to CURRENT Product Truth + formula authority."""

    try:
        blueprint = await v2svc.get_blueprint(link.v2_blueprint_id, link.v2_blueprint_revision)
    except v2svc.CopyRegisterV2Error:
        return False
    if blueprint.status != "PRODUCTION_VALID" or link.status != "PRODUCTION_VALID":
        return False
    if current_truth is None:
        return False
    if (
        link.product_truth_snapshot_version != current_truth["version"]
        or link.product_truth_snapshot_digest != current_truth["digest"]
    ):
        return False
    if link.formula_version != v2_formula_version(link.formula_id):
        return False
    return True


async def production_capacity(product_id: str) -> dict[str, Any]:
    """4-tier production capacity for a product.

    Deliberately NOT a naive Cartesian product of creative dimensions: PRODUCTION
    capacity is bounded by deployable executable copy and is further gated by
    approved visual/treatment/choreography supply and P6 constraints at plan time.
    """

    db = await get_db()
    semantic = (
        await (
            await db.execute(
                "SELECT COUNT(DISTINCT master_id) FROM master_storyboard_v3 "
                "WHERE product_id=? AND status='APPROVED'",
                (product_id,),
            )
        ).fetchone()
    )[0]
    projection = (
        await (
            await db.execute(
                "SELECT COUNT(DISTINCT projection_id) FROM duration_projection_v3 "
                "WHERE product_id=? AND status='APPROVED'",
                (product_id,),
            )
        ).fetchone()
    )[0]

    current_truth = await _current_truth(product_id)
    links = await supply_repo.list_links_for_product(product_id, limit=4096)
    executable = 0
    stale = 0
    for link in links:
        if await _link_is_executable(link, current_truth):
            executable += 1
        else:
            stale += 1

    return {
        "product_id": product_id,
        "semantic_capacity": int(semantic),
        "projection_capacity": int(projection),
        "executable_copy_capacity": executable,
        "stale_copy_count": stale,
        # Deployable executable copy; real output is further bounded by approved
        # visual/treatment/choreography supply + P6 constraints (never Cartesian).
        "production_capacity": executable,
        "production_capacity_note": (
            "PRODUCTION_CAPACITY is deployable executable copy. Real production "
            "output is additionally bounded by approved visual/treatment/"
            "choreography supply and P6 production constraints, and is never the "
            "naive product of independent creative dimensions."
        ),
    }
