"""Zero-credit P6 rehearsal against an explicitly isolated FLOW_AGENT_DIR."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-root", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


async def _run(db_root: Path) -> dict[str, object]:
    canonical_root = Path(__file__).resolve().parents[1]
    resolved_root = db_root.resolve()
    if resolved_root == canonical_root:
        raise RuntimeError("CANONICAL_FLOW_AGENT_DIR_REFUSED")
    database_path = resolved_root / "flow_agent.db"
    if not database_path.is_file():
        raise RuntimeError(f"ISOLATED_DATABASE_NOT_FOUND:{database_path}")
    os.environ["FLOW_AGENT_DIR"] = str(resolved_root)
    sys.path.insert(0, str(canonical_root))

    from agent.db.schema import close_db, get_db, init_db
    from agent.db import creative_production_crud as p6db
    from agent.models.creative_production import (
        CreativePoolSelection,
        DryRunRequest,
        PlanActionRequest,
        PoolAuthorityRequest,
        ProductionPlanCreateRequest,
        WaveAssignmentRequest,
    )
    from agent.services import creative_production_compile_service as compiler
    from agent.services import creative_production_plan_service as plans
    from agent.services import creative_production_scheduler_service as scheduler

    await init_db()
    try:
        db = await get_db()
        integrity = (await (await db.execute("PRAGMA integrity_check")).fetchone())[0]
        rehearsal_lane = await p6db.patch_lane(
            "google-flow-image-primary",
            health_status="HEALTHY",
            enabled=True,
            runtime_proof_status="VERIFIED",
            evidence_reference="ISOLATED_ZERO_CREDIT_REHEARSAL_ONLY",
            updated_at=datetime.now(UTC).isoformat(),
        )

        # The isolated database is immutable except for P6 rehearsal rows. Cache the
        # expensive 659-row P5.8 matrix within this process only; production service
        # calls retain their normal drift checks.
        authority_report = await plans.build_catalog_authority_matrix()

        async def _stable_authority_report():
            return authority_report

        plans.build_catalog_authority_matrix = _stable_authority_report
        authority = await plans.load_p58_cohort_authority()
        placeholders = ",".join("?" for _ in authority.product_ids)
        candidate = await (
            await db.execute(
                "SELECT c.product_id,c.copy_set_id,a.asset_id,a.media_id "
                "FROM copy_set c "
                "JOIN product p ON p.id=c.product_id "
                "JOIN creative_asset a ON a.product_id=c.product_id "
                f"WHERE c.product_id IN ({placeholders}) "
                "AND c.status='COPY_APPROVED' "
                "AND COALESCE(c.archived,0)=0 "
                "AND COALESCE(c.usage_count,0)<15 "
                "AND a.status='ACTIVE' "
                "AND a.review_status='APPROVED' "
                "AND a.semantic_role='PRODUCT_REFERENCE' "
                "ORDER BY c.product_id,c.copy_set_id LIMIT 1",
                tuple(authority.product_ids),
            )
        ).fetchone()
        if candidate is None:
            raise RuntimeError("NO_ZERO_CREDIT_REHEARSAL_CANDIDATE")
        product_id = str(candidate[0])
        copy_set_id = str(candidate[1])
        product_reference_asset_id = str(candidate[2])
        existing_flow_media_id = str(candidate[3] or "")
        rehearsal_flow_media_id = (
            existing_flow_media_id or "00000000-0000-4000-8000-000000000006"
        )
        if not existing_flow_media_id:
            await db.execute(
                "UPDATE creative_asset SET media_id=? WHERE asset_id=?",
                (rehearsal_flow_media_id, product_reference_asset_id),
            )
            await db.commit()
        governed = await plans.get_governed_pool_authority(
            PoolAuthorityRequest(
                product_ids=[product_id],
                logical_mode="F2V",
            )
        )
        if governed["blockers"]:
            raise RuntimeError(
                "GOVERNED_POOL_BLOCKED:"
                + json.dumps(governed["blockers"], sort_keys=True)
            )

        plan = await plans.create_plan(
            ProductionPlanCreateRequest(
                request_id=f"p6-rehearsal-create-{uuid.uuid4().hex}",
                operator_id="p6-isolated-rehearsal",
                name="P6 isolated governed image rehearsal",
                campaign_key="P6_REHEARSAL_ZERO_CREDIT",
                product_ids=[product_id],
                target_image_count=1,
                operating_window_hours=12,
                logical_mode="F2V",
                model_keys=["NANO_BANANA_PRO"],
                duration_seconds=[8],
                pools=CreativePoolSelection(
                    copy_set_ids=[copy_set_id],
                    product_reference_asset_ids=[product_reference_asset_id],
                ),
            )
        )
        preflight = await plans.run_capacity_preflight(
            plan["plan_id"],
            PlanActionRequest(
                request_id=f"p6-rehearsal-preflight-{uuid.uuid4().hex}",
                operator_id="p6-isolated-rehearsal",
            ),
        )
        if preflight.status != "PREFLIGHT_READY":
            raise RuntimeError(
                "PREFLIGHT_BLOCKED:"
                + json.dumps(preflight.blockers, sort_keys=True)
            )
        matrix = await plans.materialize_content_matrix(
            plan["plan_id"],
            PlanActionRequest(
                request_id=f"p6-rehearsal-matrix-{uuid.uuid4().hex}",
                operator_id="p6-isolated-rehearsal",
            ),
        )
        compiled = await compiler.compile_plan(
            plan["plan_id"],
            PlanActionRequest(
                request_id=f"p6-rehearsal-compile-{uuid.uuid4().hex}",
                operator_id="p6-isolated-rehearsal",
            ),
        )
        if compiled["status"] != "PENDING_APPROVAL":
            raise RuntimeError(
                "COMPILATION_BLOCKED:"
                + json.dumps(compiled["failures"], sort_keys=True)
            )
        approved = await plans.approve_plan(
            plan["plan_id"],
            request_id=f"p6-rehearsal-approve-{uuid.uuid4().hex}",
            operator_id="p6-isolated-rehearsal",
        )
        waves = await plans.assign_waves(
            plan["plan_id"],
            WaveAssignmentRequest(
                request_id=f"p6-rehearsal-waves-{uuid.uuid4().hex}",
                operator_id="p6-isolated-rehearsal",
                wave_count=1,
                batch_size=1,
            ),
        )
        dry_run = await scheduler.dry_run_plan(
            plan["plan_id"],
            DryRunRequest(
                request_id=f"p6-rehearsal-dry-{uuid.uuid4().hex}",
                operator_id="p6-isolated-rehearsal",
            ),
        )
        scheduler_result = await scheduler.scheduler_tick()
        detail = await plans.get_plan_detail(plan["plan_id"])
        return {
            "database_path": str(database_path),
            "integrity_check": integrity,
            "cohort_count": authority.cohort_count,
            "cohort_sha256": authority.cohort_sha256,
            "cohort_matches_frozen": authority.matches_frozen_authority,
            "candidate_product_id": product_id,
            "copy_set_id": copy_set_id,
            "product_reference_asset_id": product_reference_asset_id,
            "isolated_reference_media_evidence": {
                "media_id": rehearsal_flow_media_id,
                "source": (
                    "EXISTING_ISOLATED_SNAPSHOT"
                    if existing_flow_media_id
                    else "ISOLATED_SIMULATED_FLOW_UUID_NO_PROVIDER_CALL"
                ),
            },
            "pool_blockers": governed["blockers"],
            "isolated_lane_evidence": {
                "lane_id": rehearsal_lane["lane_id"],
                "runtime_proof_status": rehearsal_lane["runtime_proof_status"],
                "evidence_reference": rehearsal_lane["evidence_reference"],
            },
            "preflight_status": preflight.status,
            "safe_capacity": preflight.safe_capacity,
            "matrix_items": len(matrix["items"]),
            "compile_status": compiled["status"],
            "approved_status": approved["status"],
            "wave_count": len(waves["waves"]),
            "dry_run": {
                "checked": dry_run["checked"],
                "ready": dry_run["ready"],
                "blocked": dry_run["blocked"],
                "credit_spend": dry_run["credit_spend"],
                "provider_media_calls": dry_run["provider_media_calls"],
            },
            "scheduler_tick": scheduler_result,
            "audit_event_count": len(detail.audit_events),
            "live_execution_certified": scheduler.live_execution_certified(),
        }
    finally:
        await close_db()


def main() -> int:
    args = _arguments()
    result = asyncio.run(_run(args.db_root))
    rendered = json.dumps(result, indent=2, sort_keys=True)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
