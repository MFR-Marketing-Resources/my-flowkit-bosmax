"""Durable P6 lane scheduling, attempts, recovery, controls and QA."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import socket
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from agent.db import creative_production_crud as p6db
from agent.db import crud
from agent.models.creative_production import (
    AttemptState,
    AttemptTransitionRequest,
    DryRunRequest,
    ItemStatus,
    LanePatchRequest,
    P6_LIVE_CONFIRMATION,
    PlanActionRequest,
    PlanStatus,
    QaDecisionRequest,
    StartPlanRequest,
)
from agent.services import make_video
from agent.services import production_queue_service
from agent.services.creative_production_plan_service import (
    CreativeProductionError,
    _decode_row,
    _loads,
    _now,
    _require_plan,
    _sha,
    _stable_json,
    record_audit_event,
    resolve_item_treatment,
    require_complete_plan_snapshot,
)


LEASE_SECONDS = 300
SCHEDULER_POLL_SECONDS = 5
logger = logging.getLogger(__name__)

ATTEMPT_TRANSITIONS: dict[str, set[str]] = {
    AttemptState.NOT_SUBMITTED.value: {
        AttemptState.SUBMISSION_STARTED.value,
        AttemptState.CANCELLED.value,
        AttemptState.FAILED.value,
    },
    AttemptState.SUBMISSION_STARTED.value: {
        AttemptState.SUBMISSION_OUTCOME_UNCERTAIN.value,
        AttemptState.PROVIDER_JOB_KNOWN.value,
        AttemptState.FAILED.value,
    },
    AttemptState.SUBMISSION_OUTCOME_UNCERTAIN.value: {
        AttemptState.PROVIDER_JOB_KNOWN.value,
        AttemptState.FAILED.value,
        AttemptState.CANCELLED.value,
    },
    AttemptState.PROVIDER_JOB_KNOWN.value: {
        AttemptState.GENERATED_NOT_RETRIEVED.value,
        AttemptState.RETRIEVED_NOT_REGISTERED.value,
        AttemptState.REGISTERED.value,
        AttemptState.FAILED.value,
    },
    AttemptState.GENERATED_NOT_RETRIEVED.value: {
        AttemptState.RETRIEVED_NOT_REGISTERED.value,
        AttemptState.REGISTERED.value,
        AttemptState.FAILED.value,
    },
    AttemptState.RETRIEVED_NOT_REGISTERED.value: {
        AttemptState.REGISTERED.value,
        AttemptState.FAILED.value,
    },
    AttemptState.REGISTERED.value: {
        AttemptState.QA_REJECTED.value,
        AttemptState.SUPERSEDED.value,
    },
    AttemptState.QA_REJECTED.value: {
        AttemptState.REPLACEMENT_REQUESTED.value,
        AttemptState.SUPERSEDED.value,
    },
    AttemptState.REPLACEMENT_REQUESTED.value: {
        AttemptState.SUPERSEDED.value,
    },
    AttemptState.FAILED.value: {
        AttemptState.SUPERSEDED.value,
    },
    AttemptState.CANCELLED.value: set(),
    AttemptState.SUPERSEDED.value: set(),
}

_PROVIDER_SNAPSHOT_KEYS = (
    "job_id",
    "status",
    "stage",
    "mode",
    "project_id",
    "binding",
    "approved",
    "generation_started",
    "generation_identity",
    "identity_captured",
    "identity_gap_sse",
    "tools_seen",
    "gen_tool_matched",
    "model",
    "model_used",
    "model_unverified",
    "duration_used",
    "duration_unverified",
    "num_videos",
    "media_id",
    "media_ids",
    "artifacts",
    "artifact",
    "local_path",
    "size_mb",
    "credit_state",
    "credit_spent_likely",
    "correlation_stats",
    "output_correlation",
    "recovery_required",
    "recovery_hint",
    "error",
    "original_error",
    "artifact_record_error",
    "created",
)
_PROVIDER_TERMINAL_FAILURE_STATES = {
    "FAILED",
    "ERROR",
    "CANCELLED",
    "RENDER_NOT_MATERIALIZED",
    "STALE_OR_FOREIGN_CANDIDATES_ONLY",
}


def _provider_snapshot(job: dict[str, Any]) -> dict[str, Any]:
    selected = {
        key: job.get(key)
        for key in _PROVIDER_SNAPSHOT_KEYS
        if key in job
    }
    return json.loads(json.dumps(selected, ensure_ascii=False, default=str))


def _provider_correlation_id(job: dict[str, Any]) -> str | None:
    identity = job.get("generation_identity")
    if not isinstance(identity, dict):
        return None
    value = identity.get("tool_call_id") or identity.get("response_id")
    return str(value) if value else None


async def _persist_provider_observation(
    attempt: dict[str, Any],
    job: dict[str, Any],
) -> dict[str, Any]:
    snapshot = _provider_snapshot(job)
    previous = _loads(attempt.get("provider_snapshot_json"), {})
    if isinstance(previous, dict):
        previous = {
            key: value
            for key, value in previous.items()
            if key != "observed_at"
        }
    if previous == snapshot:
        return attempt
    observed_at = _now()
    project_id = job.get("project_id")
    if not project_id and isinstance(job.get("binding"), dict):
        project_id = job["binding"].get("project_id")
    snapshot["observed_at"] = observed_at
    return await p6db.update_attempt(
        str(attempt["attempt_id"]),
        provider_project_id=str(project_id) if project_id else None,
        provider_correlation_id=_provider_correlation_id(job),
        provider_snapshot_json=_stable_json(snapshot),
        provider_snapshot_updated_at=observed_at,
        updated_at=observed_at,
    )


def live_execution_certified() -> bool:
    return production_queue_service.bulk_live_execution_certified()


def _payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()


async def list_lanes() -> list[dict[str, Any]]:
    leases = await p6db.list_leases(active_only=True)
    lease_counts: dict[str, int] = {}
    for lease in leases:
        lane_id = str(lease["lane_id"])
        lease_counts[lane_id] = lease_counts.get(lane_id, 0) + 1
    return [
        {
            **_decode_row(lane),
            "active_lease_count": lease_counts.get(str(lane["lane_id"]), 0),
        }
        for lane in await p6db.list_lanes()
    ]


async def patch_lane(
    lane_id: str,
    body: LanePatchRequest,
) -> dict[str, Any]:
    existing = await p6db.get_lane(lane_id)
    if existing is None:
        raise CreativeProductionError(
            "LANE_NOT_FOUND",
            f"Execution lane {lane_id} was not found.",
            status_code=404,
        )
    if (
        body.enabled
        and body.runtime_proof_status != "VERIFIED"
    ):
        raise CreativeProductionError(
            "UNVERIFIED_LANE_ENABLE_FORBIDDEN",
            "An unverified lane cannot be enabled.",
            status_code=409,
        )
    row = await p6db.patch_lane(
        lane_id,
        health_status=body.health_status,
        enabled=body.enabled,
        runtime_proof_status=body.runtime_proof_status,
        evidence_reference=body.evidence_reference,
        updated_at=_now(),
    )
    return _decode_row(row)


async def _build_item_payload(
    item: dict[str, Any],
    plan: dict[str, Any],
    *,
    aspect: str,
) -> tuple[dict[str, Any], list[str]]:
    media_type = str(item["media_type"])
    package = _loads(item.get("prompt_package_json"), {})
    dimensions = _loads(item.get("creative_dimensions_json"), {})
    model_key = str(dimensions.get("model_key") or "")
    duration_seconds = int(dimensions.get("duration_seconds") or 8)
    treatment: dict[str, Any] | None = None
    if media_type == "VIDEO":
        try:
            treatment = await resolve_item_treatment(dimensions, plan)
        except CreativeProductionError as exc:
            return {}, [exc.code]
        package_lineage = package.get("treatment_lineage")
        if not isinstance(package_lineage, dict):
            return {}, ["TREATMENT_LINEAGE_REQUIRED"]
        expected_lineage = {
            "treatment_id": treatment["treatment_id"],
            "treatment_sha256": treatment["treatment_sha256"],
            "visual_fingerprint_sha256": treatment[
                "visual_fingerprint_sha256"
            ],
            "dependency_hashes": treatment["dependency_hashes"],
            "variation_group": treatment["variation_group"],
            "format": treatment["format"],
        }
        if package_lineage != expected_lineage:
            return {}, ["TREATMENT_HASH_STALE"]
    if media_type == "POSTER":
        prompt = (
            package.get("final_prompt_text")
            or package.get("prompt")
            or _stable_json(package.get("package") or package)
        )
        if not str(prompt).strip():
            return {}, ["EMPTY_POSTER_PROMPT"]
        return (
            {
                "mode": "IMG",
                "prompt": str(prompt),
                "aspect": aspect,
                "image_model": model_key or None,
                "num_videos": 1,
                "logical_mode": "POSTER",
                "execution_lane": "IMAGE_API_FIRST",
            },
            [],
        )
    wgp_id = item.get("workspace_generation_package_id")
    if not wgp_id:
        return {}, ["WORKSPACE_GENERATION_PACKAGE_REQUIRED"]
    wgp = await crud.get_workspace_generation_package(str(wgp_id))
    if wgp is None:
        return {}, ["WORKSPACE_GENERATION_PACKAGE_NOT_FOUND"]
    generation_mode = str(
        wgp.get("generation_mode")
        or package.get("generation_mode")
        or "SINGLE"
    ).upper()
    if media_type == "VIDEO" and generation_mode != "SINGLE":
        return {}, ["TREATMENT_EXTEND_UNSUPPORTED"]
    if media_type == "VIDEO" and generation_mode == "EXTEND":
        resolved, blockers = (
            production_queue_service.extend_execution_preconditions(
                wgp,
                {
                    "model": model_key,
                    "aspect": aspect,
                },
            )
        )
        video_job_id = str(package.get("video_job_id") or "")
        video_job_fingerprint = str(
            package.get("video_job_plan_fingerprint") or ""
        )
        if not video_job_id or not video_job_fingerprint:
            blockers.append("EXTEND_VIDEO_JOB_PLAN_REQUIRED")
        total_seconds = int(
            resolved.get("total_seconds")
            or package.get("requested_total_duration_seconds")
            or duration_seconds
        )
        block_seconds = int(
            package.get("engine_block_duration_seconds") or 8
        )
        return (
            {
                "mode": str(resolved.get("logical_mode") or item["logical_mode"]),
                "logical_mode": str(
                    resolved.get("logical_mode") or item["logical_mode"]
                ),
                "generation_mode": "EXTEND",
                "execution_lane": "VIDEO_JOBS_ORCHESTRATOR",
                "workspace_generation_package_id": str(wgp_id),
                "workspace_execution_package_id": resolved.get(
                    "execution_package_id"
                ),
                "video_job_id": video_job_id,
                "video_job_plan_fingerprint": video_job_fingerprint,
                "model": model_key,
                "aspect": aspect,
                "requested_total_duration_seconds": total_seconds,
                "duration_s": total_seconds,
                "engine_block_duration_seconds": block_seconds,
                "segment_count": total_seconds // block_seconds,
                "num_videos": 1,
            },
            blockers,
        )
    if media_type == "IMAGE":
        prompt = str(wgp.get("final_prompt_text") or "")
        blockers = [] if prompt.strip() else ["EMPTY_FINAL_PROMPT"]
        image_media_ids: list[str] = []
        slots = _loads(wgp.get("resolved_engine_slots_json"), {})
        if isinstance(slots, dict):
            for slot_key, asset_ref in slots.items():
                if not asset_ref:
                    continue
                media_id = await _resolve_flow_media_id(str(asset_ref), wgp)
                if media_id:
                    if media_id not in image_media_ids:
                        image_media_ids.append(media_id)
                else:
                    blockers.append(f"SLOT_NOT_UPLOADED_TO_FLOW:{slot_key}")
        return (
            {
                "mode": "IMG",
                "prompt": prompt,
                "image_media_ids": image_media_ids or None,
                "aspect": aspect,
                "image_model": model_key or None,
                "num_videos": 1,
                "logical_mode": "IMG",
                "execution_lane": "IMAGE_API_FIRST",
            },
            blockers,
        )
    payload, blockers = await production_queue_service.build_execution_payload(
        wgp,
        {
            "model": model_key,
            "model_key": model_key,
            "duration_s": duration_seconds,
            "aspect": aspect,
            "count": 1,
        },
    )
    if treatment is not None:
        payload["creative_treatment_lineage"] = {
            "treatment_id": treatment["treatment_id"],
            "treatment_sha256": treatment["treatment_sha256"],
            "visual_fingerprint_sha256": treatment[
                "visual_fingerprint_sha256"
            ],
            "dependency_hashes": treatment["dependency_hashes"],
            "variation_group": treatment["variation_group"],
            "format": treatment["format"],
        }
        payload["compiled_shot_grammar"] = treatment["shot_grammar"]
    return payload, blockers


async def _resolve_flow_media_id(
    asset_ref: str,
    package: dict[str, Any],
) -> str | None:
    try:
        return str(uuid.UUID(asset_ref))
    except (ValueError, AttributeError):
        pass
    if asset_ref.startswith("product-image:"):
        product = await crud.get_product(str(package.get("product_id") or ""))
        candidate = str((product or {}).get("media_id") or "")
    else:
        try:
            asset = await crud.get_creative_asset(asset_ref)
        except Exception:
            asset = None
        candidate = str((asset or {}).get("media_id") or "")
    try:
        return str(uuid.UUID(candidate))
    except (ValueError, AttributeError):
        return None


async def _create_attempt(
    item: dict[str, Any],
    *,
    action_request_id: str,
    actor_id: str,
    payload: dict[str, Any],
    credit_spend_intended: bool,
) -> dict[str, Any]:
    existing = await p6db.get_attempt_by_action(
        item["item_id"],
        action_request_id,
    )
    if existing is not None:
        if existing["payload_sha256"] != _payload_hash(payload):
            raise CreativeProductionError(
                "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD",
                "Action request already identifies a different attempt payload.",
                status_code=409,
            )
        return existing
    prior = await p6db.list_attempts(item["plan_id"])
    item_prior = [
        attempt
        for attempt in prior
        if attempt["item_id"] == item["item_id"]
    ]
    attempt_number = len(item_prior) + 1
    idempotency_key = _sha(
        [
            item["item_id"],
            attempt_number,
            action_request_id,
            _payload_hash(payload),
        ]
    )
    now = _now()
    return await p6db.create_attempt(
        {
            "attempt_id": f"p6attempt_{uuid.uuid4().hex[:20]}",
            "item_id": item["item_id"],
            "attempt_number": attempt_number,
            "idempotency_key": idempotency_key,
            "action_request_id": action_request_id,
            "provider": "GOOGLE_FLOW_API_FIRST",
            "engine": str(payload.get("engine") or "make_video.start_generate"),
            "model_key": str(
                payload.get("model_key") or payload.get("model") or ""
            ),
            "duration_seconds": (
                payload.get("duration_seconds") or payload.get("duration_s")
            ),
            "last_actor_id": actor_id,
            "last_action_request_id": action_request_id,
            "attempt_state": AttemptState.NOT_SUBMITTED.value,
            "payload_snapshot_json": _stable_json(payload),
            "payload_sha256": _payload_hash(payload),
            "credit_spend_intended": int(credit_spend_intended),
            "created_at": now,
            "updated_at": now,
        }
    )


async def dry_run_plan(
    plan_id: str,
    body: DryRunRequest,
) -> dict[str, Any]:
    plan = await _require_plan(plan_id)
    if plan["status"] not in {
        PlanStatus.APPROVED.value,
        PlanStatus.SCHEDULED.value,
        PlanStatus.PAUSED.value,
    }:
        raise CreativeProductionError(
            "PLAN_NOT_APPROVED",
            "Dry-run validation requires an approved plan.",
            status_code=409,
        )
    items = await p6db.list_items(
        plan_id,
        statuses=["APPROVED", "WAVE_ASSIGNED", "QUEUED"],
    )
    if not items:
        raise CreativeProductionError(
            "NO_DRY_RUN_ITEMS",
            "No approved or assigned items are available for dry run.",
            status_code=409,
        )
    reports: list[dict[str, Any]] = []
    for item in items:
        payload, blockers = await _build_item_payload(
            item,
            plan,
            aspect=body.aspect,
        )
        action_id = f"{body.request_id}:{item['item_id']}:dry"
        attempt = await _create_attempt(
            item,
            action_request_id=action_id,
            actor_id=body.operator_id,
            payload=payload,
            credit_spend_intended=False,
        )
        reports.append(
            {
                "item_id": item["item_id"],
                "attempt_id": attempt["attempt_id"],
                "payload_sha256": attempt["payload_sha256"],
                "ok": not blockers,
                "blockers": blockers,
                "credit_spend": 0,
            }
        )
    blocked = sum(not report["ok"] for report in reports)
    await record_audit_event(
        plan_id=plan_id,
        request_id=body.request_id,
        actor_id=body.operator_id,
        action="DRY_RUN_PLAN",
        source_state=str(plan["status"]),
        target_state=str(plan["status"]),
        evidence={
            "checked": len(reports),
            "blocked": blocked,
            "credit_spend": 0,
            "provider_media_calls": 0,
        },
    )
    return {
        "plan_id": plan_id,
        "checked": len(reports),
        "ready": len(reports) - blocked,
        "blocked": blocked,
        "items": reports,
        "credit_spend": 0,
        "provider_media_calls": 0,
        "note": "DRY RUN — nothing fired and no media credits were spent.",
    }


def _eligible_lane(lane: dict[str, Any], media_type: str) -> bool:
    eligible = _loads(lane.get("eligible_media_types_json"), [])
    return (
        bool(lane.get("enabled"))
        and lane.get("runtime_proof_status") == "VERIFIED"
        and lane.get("health_status") == "HEALTHY"
        and media_type in eligible
    )


async def _acquire_item_lease(
    item: dict[str, Any],
    attempt: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    lanes = [
        lane
        for lane in await p6db.list_lanes()
        if _eligible_lane(lane, str(item["media_type"]))
    ]
    if not lanes:
        raise CreativeProductionError(
            "NO_VERIFIED_HEALTHY_LANE",
            f"No verified healthy lane can execute {item['media_type']}.",
            status_code=409,
        )
    acquired_at = datetime.now(UTC)
    expires_at = acquired_at + timedelta(seconds=LEASE_SECONDS)
    for lane in lanes:
        lease = await p6db.acquire_lease(
            lane_id=lane["lane_id"],
            attempt_id=attempt["attempt_id"],
            lease_id=f"p6lease_{uuid.uuid4().hex[:20]}",
            lease_token=uuid.uuid4().hex,
            owner_instance_id=f"{socket.gethostname()}:{os.getpid()}",
            acquired_at=acquired_at.isoformat(),
            expires_at=expires_at.isoformat(),
        )
        if lease is not None:
            await p6db.update_attempt(
                attempt["attempt_id"],
                lane_id=lane["lane_id"],
                updated_at=_now(),
            )
            return lane, lease
    raise CreativeProductionError(
        "LANE_CAPACITY_EXHAUSTED",
        "All eligible verified lane slots are leased.",
        status_code=409,
    )


async def _dispatch_attempt(
    item: dict[str, Any],
    attempt: dict[str, Any],
    *,
    credit_confirmation: str,
) -> dict[str, Any]:
    lane, lease = await _acquire_item_lease(item, attempt)
    now = _now()
    await p6db.update_attempt(
        attempt["attempt_id"],
        attempt_state=AttemptState.SUBMISSION_STARTED.value,
        credit_confirmation=credit_confirmation,
        submission_started_at=now,
        updated_at=now,
    )
    await p6db.update_item(
        item["item_id"],
        status=ItemStatus.DISPATCHING.value,
        updated_at=now,
    )
    payload = _loads(attempt["payload_snapshot_json"], {})
    try:
        if str(payload.get("generation_mode") or "").upper() == "EXTEND":
            result = await production_queue_service._fire_extend_via_video_jobs(
                item,
                {
                    "model": payload.get("model"),
                    "aspect": payload.get("aspect") or "9:16",
                },
                str(payload["workspace_generation_package_id"]),
            )
            if not result.get("ok"):
                raise CreativeProductionError(
                    "EXTEND_DISPATCH_FAILED",
                    str(result.get("error") or "Durable Extend dispatch failed."),
                )
        else:
            result = await make_video.start_generate(
                mode=payload["mode"],
                prompt=payload["prompt"],
                image_media_ids=payload.get("image_media_ids"),
                aspect=payload.get("aspect") or "9:16",
                model=payload.get("model"),
                duration_s=payload.get("duration_s"),
                num_videos=int(payload.get("num_videos") or 1),
                image_model=payload.get("image_model"),
            )
    except Exception as exc:
        await p6db.update_attempt(
            attempt["attempt_id"],
            attempt_state=AttemptState.SUBMISSION_OUTCOME_UNCERTAIN.value,
            failure_stage="SUBMISSION",
            failure_code=str(exc)[:300],
            recovery_class="RECONCILE_BEFORE_RESUBMIT",
            updated_at=_now(),
        )
        await p6db.release_lease(
            attempt["attempt_id"],
            released_at=_now(),
            release_reason="SUBMISSION_OUTCOME_UNCERTAIN",
        )
        await p6db.record_lane_outcome(
            str(lane["lane_id"]),
            succeeded=False,
            completed_at=_now(),
            next_available_at=(
                datetime.now(UTC)
                + timedelta(seconds=int(lane["cooldown_seconds"]))
            ).isoformat(),
        )
        raise
    provider_job_id = str(result.get("job_id") or "")
    if not provider_job_id:
        await p6db.update_attempt(
            attempt["attempt_id"],
            attempt_state=AttemptState.SUBMISSION_OUTCOME_UNCERTAIN.value,
            failure_stage="SUBMISSION",
            failure_code="PROVIDER_JOB_ID_MISSING",
            recovery_class="RECONCILE_BEFORE_RESUBMIT",
            updated_at=_now(),
        )
        await p6db.release_lease(
            attempt["attempt_id"],
            released_at=_now(),
            release_reason="PROVIDER_JOB_ID_MISSING",
        )
        await p6db.record_lane_outcome(
            str(lane["lane_id"]),
            succeeded=False,
            completed_at=_now(),
            next_available_at=(
                datetime.now(UTC)
                + timedelta(seconds=int(lane["cooldown_seconds"]))
            ).isoformat(),
        )
        raise CreativeProductionError(
            "SUBMISSION_OUTCOME_UNCERTAIN",
            "The generation door returned no durable job identity.",
            status_code=502,
        )
    attempt = await p6db.update_attempt(
        attempt["attempt_id"],
        attempt_state=AttemptState.PROVIDER_JOB_KNOWN.value,
        provider_job_id=provider_job_id,
        provider_known_at=_now(),
        updated_at=_now(),
    )
    if provider_job_id.startswith("vj_"):
        from agent.services import video_production_orchestrator as video_jobs

        initial_job = await video_jobs.get_job_status(provider_job_id)
    else:
        initial_job = make_video.get_job(provider_job_id)
    if initial_job is not None:
        attempt = await _persist_provider_observation(attempt, initial_job)
    await p6db.update_item(
        item["item_id"],
        status=ItemStatus.SUBMITTED.value,
        updated_at=_now(),
    )
    return {
        "attempt_id": attempt["attempt_id"],
        "provider_job_id": provider_job_id,
        "lease_id": lease["lease_id"],
        "status": AttemptState.PROVIDER_JOB_KNOWN.value,
    }


async def start_plan(
    plan_id: str,
    body: StartPlanRequest,
) -> dict[str, Any]:
    if not body.live:
        return await dry_run_plan(
            plan_id,
            DryRunRequest(
                request_id=body.request_id,
                operator_id=body.operator_id,
                aspect=body.aspect,
            ),
        )
    if not live_execution_certified():
        raise CreativeProductionError(
            "P6_LIVE_EXECUTION_NOT_CERTIFIED",
            "P6 live execution is disabled until separately authorized runtime proof.",
            status_code=403,
        )
    if body.credit_confirmation != P6_LIVE_CONFIRMATION:
        raise CreativeProductionError(
            "LIVE_CREDIT_CONFIRMATION_REQUIRED",
            f"Exact confirmation phrase required: {P6_LIVE_CONFIRMATION}",
            status_code=403,
        )
    plan = await _require_plan(plan_id)
    if plan["status"] != PlanStatus.SCHEDULED.value:
        raise CreativeProductionError(
            "PLAN_NOT_SCHEDULED",
            "Live execution requires a scheduled plan.",
            status_code=409,
        )
    await require_complete_plan_snapshot(plan_id)
    items = await p6db.list_items(
        plan_id,
        statuses=["WAVE_ASSIGNED", "QUEUED"],
    )
    if not items:
        raise CreativeProductionError(
            "NO_SCHEDULABLE_ITEMS",
            "No assigned items are ready for dispatch.",
            status_code=409,
        )
    item = items[0]
    payload, blockers = await _build_item_payload(
        item,
        plan,
        aspect=body.aspect,
    )
    if blockers:
        raise CreativeProductionError(
            "LIVE_DRY_RUN_BLOCKED",
            "The next item failed payload validation.",
            status_code=409,
            details={"item_id": item["item_id"], "blockers": blockers},
        )
    payload_sha = _payload_hash(payload)
    prior_attempts = await p6db.list_attempts(plan_id)
    dry_run_proof = next(
        (
            attempt
            for attempt in prior_attempts
            if attempt["item_id"] == item["item_id"]
            and not int(attempt.get("credit_spend_intended") or 0)
            and attempt["payload_sha256"] == payload_sha
            and str(attempt.get("action_request_id") or "").endswith(":dry")
        ),
        None,
    )
    if dry_run_proof is None:
        raise CreativeProductionError(
            "MATCHING_DRY_RUN_REQUIRED",
            "The next item must have a matching zero-credit dry-run proof.",
            status_code=409,
            details={"item_id": item["item_id"], "payload_sha256": payload_sha},
        )
    attempt = await _create_attempt(
        item,
        action_request_id=f"{body.request_id}:{item['item_id']}:live",
        actor_id=body.operator_id,
        payload=payload,
        credit_spend_intended=True,
    )
    result = await _dispatch_attempt(
        item,
        attempt,
        credit_confirmation=body.credit_confirmation,
    )
    policy = _loads(plan.get("execution_policy_json"), {})
    policy.update(
        {
            "live_media_authorization_granted": True,
            "live_authorized_by": body.operator_id,
            "live_authorized_at": _now(),
            "live_authorization_request_id": body.request_id,
            "live_confirmation_hash": _sha(body.credit_confirmation or ""),
        }
    )
    await p6db.update_plan(
        plan_id,
        status=PlanStatus.RUNNING.value,
        control_action="NONE",
        execution_policy_json=_stable_json(policy),
        updated_at=_now(),
    )
    await record_audit_event(
        plan_id=plan_id,
        request_id=body.request_id,
        actor_id=body.operator_id,
        action="START_LIVE_PLAN",
        source_state=PlanStatus.SCHEDULED.value,
        target_state=PlanStatus.RUNNING.value,
        item_id=str(item["item_id"]),
        attempt_id=str(attempt["attempt_id"]),
        evidence={
            "payload_sha256": str(attempt["payload_sha256"]),
            "dry_run_attempt_id": str(dry_run_proof["attempt_id"]),
            "bulk_live_execution_certified": True,
        },
    )
    return {"plan_id": plan_id, **result}


async def control_plan(
    plan_id: str,
    action: str,
    body: PlanActionRequest,
) -> dict[str, Any]:
    plan = await _require_plan(plan_id)
    now = _now()
    action = action.upper()
    if action == "PAUSE":
        if plan["status"] not in {
            PlanStatus.SCHEDULED.value,
            PlanStatus.RUNNING.value,
        }:
            raise CreativeProductionError(
                "ILLEGAL_PLAN_TRANSITION",
                f"Cannot pause a plan in {plan['status']} state.",
                status_code=409,
            )
        status = PlanStatus.PAUSED.value
        control = "PAUSE_REQUESTED"
    elif action == "RESUME":
        if plan["status"] != PlanStatus.PAUSED.value:
            raise CreativeProductionError(
                "ILLEGAL_PLAN_TRANSITION",
                f"Cannot resume a plan in {plan['status']} state.",
                status_code=409,
            )
        status = PlanStatus.SCHEDULED.value
        control = "NONE"
    elif action == "CANCEL":
        if plan["status"] in {
            PlanStatus.COMPLETED.value,
            PlanStatus.COMPLETED_WITH_FAILURES.value,
            PlanStatus.CANCELLED.value,
            PlanStatus.FAILED.value,
        }:
            return _decode_row(plan)
        status = PlanStatus.CANCELLED.value
        control = "CANCEL_REQUESTED"
        await p6db.bulk_update_item_status(
            plan_id,
            from_statuses=[
                "PLANNED",
                "COMPILED",
                "PENDING_APPROVAL",
                "APPROVED",
                "WAVE_ASSIGNED",
                "QUEUED",
            ],
            to_status=ItemStatus.CANCELLED.value,
            updated_at=now,
        )
    else:
        raise CreativeProductionError(
            "UNKNOWN_CONTROL_ACTION",
            f"Unknown plan control action {action}.",
        )
    row = await p6db.update_plan(
        plan_id,
        status=status,
        control_action=control,
        control_version=int(plan["control_version"]) + 1,
        compile_snapshot_json=_stable_json(
            {
                **_loads(plan.get("compile_snapshot_json"), {}),
                "last_control_request_id": body.request_id,
                "last_control_operator_id": body.operator_id,
            }
        ),
        updated_at=now,
    )
    await record_audit_event(
        plan_id=plan_id,
        request_id=body.request_id,
        actor_id=body.operator_id,
        action=f"{action}_PLAN",
        source_state=str(plan["status"]),
        target_state=status,
        evidence={"control_action": control},
    )
    return _decode_row(row)


async def transition_attempt(
    attempt_id: str,
    body: AttemptTransitionRequest,
) -> dict[str, Any]:
    attempt = await p6db.get_attempt(attempt_id)
    if attempt is None:
        raise CreativeProductionError(
            "ATTEMPT_NOT_FOUND",
            f"Attempt {attempt_id} was not found.",
            status_code=404,
        )
    current = str(attempt["attempt_state"])
    target = body.attempt_state.value
    if target == current:
        return _decode_row(attempt)
    if target not in ATTEMPT_TRANSITIONS.get(current, set()):
        raise CreativeProductionError(
            "ILLEGAL_ATTEMPT_TRANSITION",
            f"Attempt cannot transition from {current} to {target}.",
            status_code=409,
        )
    now = _now()
    timestamp_fields: dict[str, Any] = {}
    if target == AttemptState.PROVIDER_JOB_KNOWN.value:
        if not body.provider_job_id:
            raise CreativeProductionError(
                "PROVIDER_JOB_ID_REQUIRED",
                "PROVIDER_JOB_KNOWN requires provider_job_id.",
            )
        timestamp_fields["provider_known_at"] = now
    if target == AttemptState.GENERATED_NOT_RETRIEVED.value:
        timestamp_fields["generated_at"] = now
    if target == AttemptState.RETRIEVED_NOT_REGISTERED.value:
        timestamp_fields["retrieved_at"] = now
    if target == AttemptState.REGISTERED.value:
        if not body.artifact_media_id:
            raise CreativeProductionError(
                "ARTIFACT_MEDIA_ID_REQUIRED",
                "REGISTERED requires artifact_media_id.",
            )
        timestamp_fields.update(
            {
                "registered_at": now,
                "completed_at": now,
            }
        )
    row = await p6db.update_attempt(
        attempt_id,
        attempt_state=target,
        provider_job_id=body.provider_job_id or attempt.get("provider_job_id"),
        artifact_media_id=(
            body.artifact_media_id or attempt.get("artifact_media_id")
        ),
        failure_stage=body.failure_stage,
        failure_code=body.failure_code,
        last_actor_id=body.operator_id,
        last_action_request_id=body.request_id,
        updated_at=now,
        **timestamp_fields,
    )
    item = await p6db.get_item(str(attempt["item_id"]))
    assert item is not None
    await record_audit_event(
        plan_id=str(item["plan_id"]),
        request_id=body.request_id,
        actor_id=body.operator_id,
        action="TRANSITION_ATTEMPT",
        source_state=current,
        target_state=target,
        item_id=str(item["item_id"]),
        attempt_id=attempt_id,
        evidence={
            "provider_job_id": body.provider_job_id,
            "artifact_media_id": body.artifact_media_id,
            "failure_stage": body.failure_stage,
            "failure_code": body.failure_code,
        },
    )
    if attempt.get("lane_id") and target in {
        AttemptState.REGISTERED.value,
        AttemptState.FAILED.value,
        AttemptState.CANCELLED.value,
    }:
        lane = await p6db.get_lane(str(attempt["lane_id"]))
        if lane is not None:
            seconds = int(
                lane["min_interval_seconds"]
                if target == AttemptState.REGISTERED.value
                else lane["cooldown_seconds"]
            )
            next_available = (
                datetime.now(UTC) + timedelta(seconds=seconds)
            ).isoformat(timespec="seconds")
            await p6db.record_lane_outcome(
                str(attempt["lane_id"]),
                succeeded=target == AttemptState.REGISTERED.value,
                completed_at=now,
                next_available_at=next_available,
            )
    return _decode_row(row)


async def reconcile_attempt(attempt_id: str) -> dict[str, Any]:
    attempt = await p6db.get_attempt(attempt_id)
    if attempt is None:
        raise CreativeProductionError(
            "ATTEMPT_NOT_FOUND",
            f"Attempt {attempt_id} was not found.",
            status_code=404,
        )
    provider_job_id = str(attempt.get("provider_job_id") or "")
    if not provider_job_id:
        if attempt["attempt_state"] == AttemptState.SUBMISSION_STARTED.value:
            attempt = await p6db.update_attempt(
                attempt_id,
                attempt_state=AttemptState.SUBMISSION_OUTCOME_UNCERTAIN.value,
                recovery_class="RECONCILE_BEFORE_RESUBMIT",
                updated_at=_now(),
            )
        return {
            "attempt": _decode_row(attempt),
            "provider_state": "UNKNOWN",
            "resubmission_allowed": False,
        }
    if provider_job_id.startswith("vj_"):
        from agent.services import video_production_orchestrator as video_jobs

        try:
            video_job = await video_jobs.get_job_status(provider_job_id)
        except video_jobs.OrchestratorError:
            live_job = None
        else:
            video_status = str(video_job.get("status") or "")
            if video_status == video_jobs.S_COMPLETE:
                live_job = {
                    **video_job,
                    "status": "COMPLETED",
                    "media_id": video_job.get("final_media_id"),
                }
            elif video_status in {
                video_jobs.F_INITIAL,
                video_jobs.F_EXTEND,
                video_jobs.F_FINAL,
                video_jobs.F_AUTH,
            }:
                live_job = {
                    **video_job,
                    "status": "FAILED",
                    "error": video_job.get("error_code") or video_status,
                }
            else:
                live_job = video_job
        job_source = "VIDEO_JOBS_ORCHESTRATOR"
    else:
        live_job = make_video.get_job(provider_job_id)
        job_source = "LIVE_PROCESS"
    if live_job is None:
        artifact = await p6db.get_generated_artifact_by_job_id(provider_job_id)
        if artifact is not None:
            media_id = str(artifact["media_id"])
            now = _now()
            attempt = await p6db.update_attempt(
                attempt_id,
                attempt_state=AttemptState.REGISTERED.value,
                artifact_media_id=media_id,
                generated_at=attempt.get("generated_at") or now,
                retrieved_at=now,
                registered_at=now,
                completed_at=now,
                recovery_class="RECOVERED_FROM_GENERATED_ARTIFACT_LEDGER",
                updated_at=now,
            )
            await p6db.update_item(
                attempt["item_id"],
                status=ItemStatus.QA_PENDING.value,
                output_media_id=media_id,
                updated_at=now,
            )
            await p6db.upsert_qa(
                {
                    "qa_id": f"p6qa_{uuid.uuid4().hex[:20]}",
                    "item_id": attempt["item_id"],
                    "attempt_id": attempt_id,
                    "artifact_media_id": media_id,
                    "status": "QA_PENDING",
                    "checklist_json": "{}",
                    "created_at": now,
                    "updated_at": now,
                }
            )
            await p6db.release_lease(
                attempt_id,
                released_at=now,
                release_reason="REGISTERED_FROM_GENERATED_ARTIFACT_LEDGER",
            )
            return {
                "attempt": _decode_row(attempt),
                "provider_state": "ARTIFACT_LEDGER_REGISTERED",
                "provider_state_source": "GENERATED_ARTIFACT_LEDGER",
                "resubmission_allowed": False,
            }
        job = _loads(attempt.get("provider_snapshot_json"), {})
        if not isinstance(job, dict) or not job:
            return {
                "attempt": _decode_row(attempt),
                "provider_state": "LOCAL_JOB_STATE_UNAVAILABLE",
                "provider_state_source": "NONE",
                "resubmission_allowed": False,
                "recovery_action": "PROVIDER_RECONCILIATION_REQUIRED",
            }
        job_source = "DURABLE_PROVIDER_SNAPSHOT"
    else:
        attempt = await _persist_provider_observation(attempt, live_job)
        job = live_job
    status = str(job.get("status") or "").upper()
    media_ids: list[str] = []
    for value in job.get("media_ids") or []:
        if value and str(value) not in media_ids:
            media_ids.append(str(value))
    if job.get("media_id") and str(job["media_id"]) not in media_ids:
        media_ids.append(str(job["media_id"]))
    for artifact in job.get("artifacts") or []:
        if (
            isinstance(artifact, dict)
            and artifact.get("media_id")
            and str(artifact["media_id"]) not in media_ids
        ):
            media_ids.append(str(artifact["media_id"]))

    terminal_observation = (
        status in {"DONE", "COMPLETED", "GENERATED_BUT_UNRETRIEVED"}
        or status in _PROVIDER_TERMINAL_FAILURE_STATES
    )
    if job_source == "DURABLE_PROVIDER_SNAPSHOT" and not terminal_observation:
        return {
            "attempt": _decode_row(attempt),
            "provider_state": "LOCAL_JOB_STATE_UNAVAILABLE",
            "provider_state_source": job_source,
            "last_observed_provider_state": status or "UNKNOWN",
            "resubmission_allowed": False,
            "recovery_action": "PROVIDER_RECONCILIATION_REQUIRED",
        }

    if status in {"DONE", "COMPLETED"} and media_ids:
        media_id = media_ids[0]
        artifact = await crud.get_generated_artifact(media_id)
        now = _now()
        if artifact is not None:
            state = AttemptState.REGISTERED.value
            await p6db.update_item(
                attempt["item_id"],
                status=ItemStatus.QA_PENDING.value,
                output_media_id=media_id,
                updated_at=now,
            )
            await p6db.upsert_qa(
                {
                    "qa_id": f"p6qa_{uuid.uuid4().hex[:20]}",
                    "item_id": attempt["item_id"],
                    "attempt_id": attempt_id,
                    "artifact_media_id": media_id,
                    "status": "QA_PENDING",
                    "checklist_json": "{}",
                    "created_at": now,
                    "updated_at": now,
                }
            )
        else:
            state = AttemptState.RETRIEVED_NOT_REGISTERED.value
        attempt = await p6db.update_attempt(
            attempt_id,
            attempt_state=state,
            artifact_media_id=media_id,
            generated_at=attempt.get("generated_at") or now,
            retrieved_at=now,
            registered_at=now if state == AttemptState.REGISTERED.value else None,
            completed_at=now if state == AttemptState.REGISTERED.value else None,
            updated_at=now,
        )
        await p6db.release_lease(
            attempt_id,
            released_at=now,
            release_reason=state,
        )
    elif status == "GENERATED_BUT_UNRETRIEVED":
        now = _now()
        attempt = await p6db.update_attempt(
            attempt_id,
            attempt_state=AttemptState.GENERATED_NOT_RETRIEVED.value,
            failure_stage="RETRIEVAL",
            failure_code=str(job.get("error") or status)[:300],
            recovery_class="RETRIEVAL_ONLY_NO_RESUBMIT",
            generated_at=attempt.get("generated_at") or now,
            updated_at=now,
        )
        await p6db.update_item(
            attempt["item_id"],
            status=ItemStatus.GENERATED.value,
            updated_at=now,
        )
        await p6db.release_lease(
            attempt_id,
            released_at=now,
            release_reason=status,
        )
    elif status in _PROVIDER_TERMINAL_FAILURE_STATES:
        now = _now()
        cancelled = status == "CANCELLED"
        failure_stage = {
            "RENDER_NOT_MATERIALIZED": "PROVIDER_RENDER",
            "STALE_OR_FOREIGN_CANDIDATES_ONLY": "OUTPUT_CORRELATION",
        }.get(status, "PROVIDER_JOB")
        failure_code = f"{status}: {job.get('error') or status}"[:300]
        attempt = await p6db.update_attempt(
            attempt_id,
            attempt_state=(
                AttemptState.CANCELLED.value
                if cancelled
                else AttemptState.FAILED.value
            ),
            failure_stage=failure_stage,
            failure_code=failure_code,
            recovery_class=(
                "CANCELLED_NO_RESUBMIT"
                if cancelled
                else "NEW_GENERATION_RETRY_ALLOWED_AFTER_REVIEW"
            ),
            completed_at=now,
            updated_at=now,
        )
        await p6db.update_item(
            attempt["item_id"],
            status=(
                ItemStatus.CANCELLED.value
                if cancelled
                else ItemStatus.FAILED.value
            ),
            updated_at=now,
        )
        await p6db.release_lease(
            attempt_id,
            released_at=now,
            release_reason=status,
        )
    return {
        "attempt": _decode_row(attempt),
        "provider_state": status,
        "provider_state_source": job_source,
        "resubmission_allowed": (
            status in _PROVIDER_TERMINAL_FAILURE_STATES
            and status != "CANCELLED"
        ),
    }


async def recover_after_restart() -> dict[str, Any]:
    now = _now()
    expired = 0
    for lease in await p6db.list_leases(active_only=True):
        if str(lease["expires_at"]) <= now:
            await p6db.release_lease(
                lease["attempt_id"],
                released_at=now,
                release_reason="RESTART_EXPIRED_LEASE",
            )
            expired += 1
    uncertain = 0
    reconciled = 0
    reconciliation_pending = 0
    plans = await p6db.list_plans(limit=500)
    for plan in plans:
        for attempt in await p6db.list_attempts(plan["plan_id"]):
            if attempt["attempt_state"] != AttemptState.SUBMISSION_STARTED.value:
                continue
            await p6db.update_attempt(
                attempt["attempt_id"],
                attempt_state=AttemptState.SUBMISSION_OUTCOME_UNCERTAIN.value,
                recovery_class="RECONCILE_BEFORE_RESUBMIT",
                failure_stage="PROCESS_RESTART",
                failure_code="SUBMISSION_STATE_LOST_BEFORE_PROVIDER_ID_PERSISTED",
                updated_at=now,
            )
            uncertain += 1
        for attempt in await p6db.list_attempts(plan["plan_id"]):
            if attempt["attempt_state"] not in {
                AttemptState.PROVIDER_JOB_KNOWN.value,
                AttemptState.GENERATED_NOT_RETRIEVED.value,
                AttemptState.RETRIEVED_NOT_REGISTERED.value,
            }:
                continue
            result = await reconcile_attempt(str(attempt["attempt_id"]))
            if result["attempt"]["attempt_state"] == AttemptState.REGISTERED.value:
                reconciled += 1
            else:
                reconciliation_pending += 1
    return {
        "expired_leases_released": expired,
        "attempts_marked_uncertain": uncertain,
        "attempts_reconciled": reconciled,
        "attempts_reconciliation_pending": reconciliation_pending,
        "blind_resubmissions": 0,
        "credit_spend": 0,
    }


async def scheduler_tick() -> dict[str, Any]:
    for attempt in await p6db.list_attempts_for_reconciliation(limit=200):
        try:
            await reconcile_attempt(str(attempt["attempt_id"]))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "P6 provider reconciliation failed for attempt %s",
                attempt["attempt_id"],
            )
    if not live_execution_certified():
        return {
            "live_execution_certified": False,
            "plans_examined": 0,
            "attempts_dispatched": 0,
            "credit_spend": 0,
        }
    examined = 0
    dispatched = 0
    for plan in await p6db.list_plans(limit=500):
        if (
            plan["status"] != PlanStatus.RUNNING.value
            or plan["control_action"] != "NONE"
        ):
            continue
        policy = _loads(plan.get("execution_policy_json"), {})
        if not policy.get("live_media_authorization_granted"):
            continue
        examined += 1
        items = await p6db.list_items(
            plan["plan_id"],
            statuses=[ItemStatus.WAVE_ASSIGNED.value, ItemStatus.QUEUED.value],
        )
        if not items:
            all_items = await p6db.list_items(plan["plan_id"])
            terminal = {
                ItemStatus.QA_APPROVED.value,
                ItemStatus.QA_REJECTED.value,
                ItemStatus.FAILED.value,
                ItemStatus.CANCELLED.value,
                ItemStatus.SUPERSEDED.value,
            }
            if all_items and all(str(item["status"]) in terminal for item in all_items):
                failed = any(
                    item["status"]
                    in {
                        ItemStatus.QA_REJECTED.value,
                        ItemStatus.FAILED.value,
                        ItemStatus.CANCELLED.value,
                    }
                    for item in all_items
                )
                await p6db.update_plan(
                    plan["plan_id"],
                    status=(
                        PlanStatus.COMPLETED_WITH_FAILURES.value
                        if failed
                        else PlanStatus.COMPLETED.value
                    ),
                    updated_at=_now(),
                )
            continue
        item = items[0]
        aspect = str(policy.get("aspect") or "9:16")
        payload, blockers = await _build_item_payload(item, plan, aspect=aspect)
        if blockers:
            await p6db.update_item(
                item["item_id"],
                status=ItemStatus.FAILED.value,
                updated_at=_now(),
            )
            continue
        payload_sha = _payload_hash(payload)
        attempts = await p6db.list_attempts(plan["plan_id"])
        dry_proof = next(
            (
                attempt
                for attempt in attempts
                if attempt["item_id"] == item["item_id"]
                and not int(attempt.get("credit_spend_intended") or 0)
                and attempt["payload_sha256"] == payload_sha
                and str(attempt["action_request_id"]).endswith(":dry")
            ),
            None,
        )
        if dry_proof is None:
            continue
        action_request_id = (
            f"auto:{plan['plan_id']}:{item['item_id']}:live"
        )
        actor_id = str(policy.get("live_authorized_by") or "P6_SYSTEM")
        attempt = await _create_attempt(
            item,
            action_request_id=action_request_id,
            actor_id=actor_id,
            payload=payload,
            credit_spend_intended=True,
        )
        if attempt["attempt_state"] != AttemptState.NOT_SUBMITTED.value:
            continue
        try:
            await _dispatch_attempt(
                item,
                attempt,
                credit_confirmation=P6_LIVE_CONFIRMATION,
            )
        except CreativeProductionError:
            continue
        dispatched += 1
    return {
        "live_execution_certified": True,
        "plans_examined": examined,
        "attempts_dispatched": dispatched,
    }


async def scheduler_loop() -> None:
    while True:
        try:
            await scheduler_tick()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("P6 creative production scheduler tick failed")
        await asyncio.sleep(SCHEDULER_POLL_SECONDS)


async def retry_attempt(
    attempt_id: str,
    body: PlanActionRequest,
) -> dict[str, Any]:
    attempt = await p6db.get_attempt(attempt_id)
    if attempt is None:
        raise CreativeProductionError(
            "ATTEMPT_NOT_FOUND",
            f"Attempt {attempt_id} was not found.",
            status_code=404,
        )
    state = str(attempt["attempt_state"])
    if state == AttemptState.SUBMISSION_OUTCOME_UNCERTAIN.value:
        raise CreativeProductionError(
            "RECONCILIATION_REQUIRED_BEFORE_RETRY",
            "Uncertain submissions cannot be blindly retried.",
            status_code=409,
        )
    if state not in {
        AttemptState.FAILED.value,
        AttemptState.QA_REJECTED.value,
    }:
        raise CreativeProductionError(
            "ATTEMPT_NOT_RETRYABLE",
            f"Attempt in {state} state is not retryable.",
            status_code=409,
        )
    item = await p6db.get_item(attempt["item_id"])
    assert item is not None
    replacement = await _create_attempt(
        item,
        action_request_id=f"{body.request_id}:{item['item_id']}:retry",
        actor_id=body.operator_id,
        payload=_loads(attempt["payload_snapshot_json"], {}),
        credit_spend_intended=False,
    )
    await p6db.update_attempt(
        attempt_id,
        attempt_state=AttemptState.SUPERSEDED.value,
        completed_at=_now(),
        updated_at=_now(),
    )
    await p6db.update_item(
        item["item_id"],
        status=ItemStatus.QUEUED.value,
        updated_at=_now(),
    )
    await record_audit_event(
        plan_id=str(item["plan_id"]),
        request_id=body.request_id,
        actor_id=body.operator_id,
        action="RETRY_ATTEMPT_STAGED",
        source_state=state,
        target_state=AttemptState.NOT_SUBMITTED.value,
        item_id=str(item["item_id"]),
        attempt_id=str(replacement["attempt_id"]),
        evidence={
            "superseded_attempt_id": attempt_id,
            "credit_spend": 0,
        },
    )
    return {
        "superseded_attempt_id": attempt_id,
        "replacement_attempt": _decode_row(replacement),
        "retry_class": "NEW_GENERATION_RETRY_REQUIRES_NEW_LIVE_CONFIRMATION",
        "credit_spend": 0,
    }


async def qa_decision(
    item_id: str,
    body: QaDecisionRequest,
) -> dict[str, Any]:
    item = await p6db.get_item(item_id)
    if item is None:
        raise CreativeProductionError(
            "ITEM_NOT_FOUND",
            f"Production item {item_id} was not found.",
            status_code=404,
        )
    attempts = await p6db.list_attempts(item["plan_id"])
    registered = [
        attempt
        for attempt in attempts
        if attempt["item_id"] == item_id
        and attempt["attempt_state"] == AttemptState.REGISTERED.value
    ]
    if not registered:
        raise CreativeProductionError(
            "REGISTERED_ATTEMPT_REQUIRED",
            "QA requires a registered artifact attempt.",
            status_code=409,
        )
    attempt = registered[-1]
    media_id = str(
        attempt.get("artifact_media_id") or item.get("output_media_id") or ""
    )
    if not media_id:
        raise CreativeProductionError(
            "ARTIFACT_MEDIA_ID_REQUIRED",
            "QA requires an artifact media identity.",
            status_code=409,
        )
    now = _now()
    qa = await p6db.upsert_qa(
        {
            "qa_id": f"p6qa_{uuid.uuid4().hex[:20]}",
            "item_id": item_id,
            "attempt_id": attempt["attempt_id"],
            "artifact_media_id": media_id,
            "status": body.decision,
            "checklist_json": "{}",
            "reviewer_id": body.operator_id,
            "reviewer_note": body.reviewer_note,
            "reviewed_at": now,
            "created_at": now,
            "updated_at": now,
        }
    )
    replacement: dict[str, Any] | None = None
    if body.decision == "QA_APPROVED":
        await p6db.update_item(
            item_id,
            status=ItemStatus.QA_APPROVED.value,
            updated_at=now,
        )
    else:
        await p6db.update_item(
            item_id,
            status=ItemStatus.QA_REJECTED.value,
            updated_at=now,
        )
        await p6db.update_attempt(
            attempt["attempt_id"],
            attempt_state=AttemptState.QA_REJECTED.value,
            updated_at=now,
        )
        if body.request_replacement:
            dimensions = _loads(item["creative_dimensions_json"], {})
            dimensions["replacement_for_item_id"] = item_id
            dimensions["replacement_request_id"] = body.request_id
            dna = _sha(dimensions)
            current_items = await p6db.list_items(item["plan_id"])
            replacement_id = f"p6item_{uuid.uuid4().hex[:20]}"
            await p6db.insert_items(
                [
                    {
                        "item_id": replacement_id,
                        "plan_id": item["plan_id"],
                        "item_ordinal": len(current_items),
                        "product_id": item["product_id"],
                        "media_type": item["media_type"],
                        "logical_mode": item["logical_mode"],
                        "creative_dimensions_json": _stable_json(dimensions),
                        "creative_dna_sha256": dna,
                        "dedupe_guard_key": f"replacement:{replacement_id}:{dna}",
                        "controlled_reuse_reason": (
                            f"QA replacement for {item_id}: {body.reviewer_note}"
                        ),
                        "execution_policy_json": item[
                            "execution_policy_json"
                        ],
                        "status": ItemStatus.PLANNED.value,
                        "replacement_for_item_id": item_id,
                        "created_at": now,
                        "updated_at": now,
                    }
                ]
            )
            await p6db.update_item(
                item_id,
                status=ItemStatus.REPLACEMENT_PLANNED.value,
                replaced_by_item_id=replacement_id,
                updated_at=now,
            )
            await p6db.update_attempt(
                attempt["attempt_id"],
                attempt_state=AttemptState.REPLACEMENT_REQUESTED.value,
                updated_at=now,
            )
            replacement = _decode_row(
                (await p6db.get_item(replacement_id)) or {}
            )
    await record_audit_event(
        plan_id=str(item["plan_id"]),
        request_id=body.request_id,
        actor_id=body.operator_id,
        action="QA_DECISION",
        source_state=str(item["status"]),
        target_state=(
            ItemStatus.REPLACEMENT_PLANNED.value
            if replacement is not None
            else body.decision
        ),
        item_id=item_id,
        attempt_id=str(attempt["attempt_id"]),
        evidence={
            "artifact_media_id": media_id,
            "request_replacement": body.request_replacement,
            "replacement_item_id": (
                replacement.get("item_id") if replacement is not None else None
            ),
        },
    )
    return {
        "qa": _decode_row(qa),
        "replacement_item": replacement,
        "credit_spend": 0,
    }
