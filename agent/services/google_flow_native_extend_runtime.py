"""Native Google Flow Extend runtime orchestrator (API-first, capability-gated).

Drives the CAPTURED native-Extend contract (live evidence 2026-07-11, see
``.ai/experiments/aisandbox_extend_discovery``):

    block 1  -> existing generate lane (NOT this service; its output op id is the input)
    block 2  -> batchAsyncGenerateVideoExtendVideo(videoInput.mediaId = block1 op id)
    block 3  -> extend(videoInput.mediaId = block2 CHILD op id)
    …            each block chains off the immediately-preceding successful child.

Design invariants:
  * Direct aisandbox RPC over the existing extension relay — NOT the flowCreationAgent
    conversational one-door (`make_video.start_generate`), which is untouched.
  * Continuity is carried by ``videoInput`` + frame window, and the FULL structured
    block prompt is sent (never a compact "extend this video" phrase).
  * parent/child OPERATION id and primaryMediaId are persisted as SEPARATE fields —
    the extend binding uses the OPERATION id (block-1 op b6371e69 != media 69051c7b).
  * Fail-closed everywhere: capability gate, model resolution, missing context, and a
    hard DRY_RUN default. A live credit-consuming submit needs BOTH
    ``NATIVE_EXTEND_ENABLED=1`` AND ``confirm_live_credit_burn=True``.
  * The 16s COMBINED concatenated export stays AUTHORITY_MISSING — this service never
    substitutes the Download Project ZIP (block1.mp4 + poster) for it.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from agent import config
from agent.db import crud as _crud
from agent.services import extend_route_planner as _routes

logger = logging.getLogger(__name__)

# ── Machine-readable error codes ────────────────────────────────────────────
EXTEND_PARENT_MEDIA_ID_MISSING = "EXTEND_PARENT_MEDIA_ID_MISSING"
EXTEND_PROJECT_CONTEXT_MISSING = "EXTEND_PROJECT_CONTEXT_MISSING"
EXTEND_SCENE_CONTEXT_MISSING = "EXTEND_SCENE_CONTEXT_MISSING"
EXTEND_RUNTIME_CONTRACT_MISSING = "EXTEND_RUNTIME_CONTRACT_MISSING"
EXTEND_CAPTURE_CONTRACT_DRIFT = "EXTEND_CAPTURE_CONTRACT_DRIFT"
EXTEND_REQUEST_REJECTED = "EXTEND_REQUEST_REJECTED"
EXTEND_OPERATION_TIMEOUT = "EXTEND_OPERATION_TIMEOUT"
EXTEND_OPERATION_FAILED = "EXTEND_OPERATION_FAILED"
EXTEND_CHILD_MEDIA_ID_MISSING = "EXTEND_CHILD_MEDIA_ID_MISSING"
EXTEND_LINEAGE_MISMATCH = "EXTEND_LINEAGE_MISMATCH"
EXTEND_DUPLICATE_SUBMISSION_BLOCKED = "EXTEND_DUPLICATE_SUBMISSION_BLOCKED"
EXTEND_UNSUPPORTED_MODEL = "EXTEND_UNSUPPORTED_MODEL"
EXTEND_UNSUPPORTED_DURATION = "EXTEND_UNSUPPORTED_DURATION"
FINAL_CONCAT_EXPORT_AUTHORITY_MISSING = "FINAL_CONCAT_EXPORT_AUTHORITY_MISSING"
NATIVE_EXTEND_DISABLED = "NATIVE_EXTEND_DISABLED"
# Explicit live-intent contract (no silent live->dry-run downgrade; bounded credit).
LIVE_CREDIT_CONFIRMATION_REQUIRED = "LIVE_CREDIT_CONFIRMATION_REQUIRED"
EXTEND_CONFIRMATION_COUNT_MISMATCH = "EXTEND_CONFIRMATION_COUNT_MISMATCH"

# Terminal media-generation states (existing aisandbox constants).
TERMINAL_SUCCESS = "MEDIA_GENERATION_STATUS_SUCCESSFUL"
TERMINAL_FAILED = "MEDIA_GENERATION_STATUS_FAILED"

# lineage.polling_state machine (mirrors DB CHECK constraint).
STATE_NOT_STARTED = "NOT_STARTED"
STATE_SOURCE_READY = "SOURCE_READY"
STATE_SUBMITTED = "EXTEND_SUBMITTED"
STATE_POLLING = "EXTEND_POLLING"
STATE_SUCCEEDED = "EXTEND_SUCCEEDED"
STATE_FAILED = "EXTEND_FAILED"
STATE_HARVEST_FAILED = "HARVEST_FAILED"
STATE_CANCELLED = "CANCELLED"
STATE_BLOCKED = "BLOCKED"


class NativeExtendError(RuntimeError):
    """Explicit, machine-readable native-extend failure. ``code`` is one of the
    module-level constants above; ``detail`` carries the offending id/context."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}:{detail}" if detail else code)


def native_extend_enabled() -> bool:
    """Runtime kill-switch — defaults OFF. Live submits ALSO require an explicit
    per-call ``confirm_live_credit_burn``."""
    return os.environ.get("NATIVE_EXTEND_ENABLED", "0").strip().lower() in (
        "1", "true", "yes", "on")


# ── Contract helpers (drift detection + response parsing) ───────────────────
_REQUIRED_EXTEND_MODEL = "veo_3_1_extension_lite"


def assert_request_matches_contract(body: dict) -> None:
    """Guard the built request against the CAPTURED contract; raise
    EXTEND_CAPTURE_CONTRACT_DRIFT on any structural divergence. This is the
    drift tripwire: if a future refactor changes the emitted shape, live extend
    fails closed instead of firing a silently-wrong request."""
    try:
        if body.get("useV2ModelConfig") is not True:
            raise NativeExtendError(EXTEND_CAPTURE_CONTRACT_DRIFT, "useV2ModelConfig!=true")
        mgc = body["mediaGenerationContext"]
        if mgc.get("audioFailurePreference") != "BLOCK_SILENCED_VIDEOS":
            raise NativeExtendError(EXTEND_CAPTURE_CONTRACT_DRIFT, "audioFailurePreference")
        sc = mgc["sceneContext"]
        if not sc.get("sceneId") or "position" not in sc:
            raise NativeExtendError(EXTEND_CAPTURE_CONTRACT_DRIFT, "sceneContext")
        req = body["requests"][0]
        vi = req["videoInput"]
        if not vi.get("mediaId"):
            raise NativeExtendError(EXTEND_CAPTURE_CONTRACT_DRIFT, "videoInput.mediaId")
        if "startFrameIndex" not in vi or "endFrameIndex" not in vi:
            raise NativeExtendError(EXTEND_CAPTURE_CONTRACT_DRIFT, "videoInput.frameIndex")
        if req.get("videoModelKey") != _REQUIRED_EXTEND_MODEL:
            raise NativeExtendError(EXTEND_CAPTURE_CONTRACT_DRIFT,
                                    f"videoModelKey={req.get('videoModelKey')}")
        req["textInput"]["structuredPrompt"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise NativeExtendError(EXTEND_CAPTURE_CONTRACT_DRIFT, str(exc)) from exc


def extract_extend_child(response: dict) -> Optional[dict]:
    """Pull the child identity from a SYNCHRONOUS batchAsyncGenerateVideoExtendVideo
    response (captured record 631). child op id = ``media[0].name`` (==
    ``workflows[0].metadata.primaryMediaId``)."""
    media = (response or {}).get("media") or []
    if not media:
        return None
    m0 = media[0]
    meta = m0.get("mediaMetadata") or {}
    status = (meta.get("mediaStatus") or m0.get("mediaStatus") or {}).get(
        "mediaGenerationStatus")
    workflows = (response or {}).get("workflows") or []
    wf_meta = (workflows[0].get("metadata") or {}) if workflows else {}
    return {
        "child_operation_id": m0.get("name"),
        "child_primary_media_id": wf_meta.get("primaryMediaId") or m0.get("name"),
        "child_workflow_id": m0.get("workflowId") or (
            workflows[0].get("name") if workflows else None),
        "batch_id": wf_meta.get("batchId"),
        "status": status,
        "length": (((m0.get("video") or {}).get("dimensions") or {}).get("length")),
    }


def _status_from_poll(resp: dict, child_op: str) -> Optional[str]:
    for m in (resp or {}).get("media") or []:
        if m.get("name") and child_op and m.get("name") != child_op:
            continue
        ms = m.get("mediaStatus") or (m.get("mediaMetadata") or {}).get("mediaStatus") or {}
        return ms.get("mediaGenerationStatus")
    return None


def _extract_media_url(media: dict) -> Optional[str]:
    if not isinstance(media, dict):
        return None
    for scope in (media, media.get("media") or {}, media.get("video") or {}):
        for k in ("fifeUrl", "servingUri", "downloadUrl", "url", "servingUrl"):
            if isinstance(scope, dict) and scope.get(k):
                return scope[k]
    return None


def _prompt_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _idempotency_key(project_id: str, scene_id: str, position: int, prompt_hash: str,
                     parent_operation_id: str) -> str:
    """Idempotency identity is PARENT-AWARE. Including the parent operation id means
    the same prompt at the same position against a DIFFERENT parent (regenerated
    source, reused prompt on a new lineage, rerun after a failed source) is a
    genuinely NEW extension and must not reuse the old child. Same (project, scene,
    position, prompt, parent) is the only thing that dedups a duplicate credit spend."""
    return hashlib.sha256(
        f"{project_id}|{scene_id}|{position}|{prompt_hash}|{parent_operation_id}".encode(
            "utf-8")).hexdigest()


# ── Request model ───────────────────────────────────────────────────────────
@dataclass
class ExtendBlock:
    """One continuation block (block index >= 2). ``prompt`` is the FULL structured
    block prompt; ``position`` is the 0-based sceneContext.position."""
    block_index: int
    position: int
    prompt: str
    is_final: bool = False
    start_frame_index: int = 1
    end_frame_index: int = 24


@dataclass
class ExtendChainRequest:
    project_id: str
    scene_id: str
    source_operation_id: str  # block-1 operation id — parent for block 2
    blocks: list = field(default_factory=list)  # ExtendBlock, blocks 2..N only
    aspect_ratio: str = "VIDEO_ASPECT_RATIO_PORTRAIT"
    workspace_generation_package_id: Optional[str] = None
    seed: Optional[int] = None
    user_paygate_tier: str = "PAYGATE_TIER_TWO"


def _validate_context(req: ExtendChainRequest) -> str:
    """Fail-closed context validation shared by plan + execute. Returns the
    resolved model key (also fail-closed on unsupported aspect)."""
    if not req.project_id:
        raise NativeExtendError(EXTEND_PROJECT_CONTEXT_MISSING)
    if not req.scene_id:
        raise NativeExtendError(EXTEND_SCENE_CONTEXT_MISSING)
    if not req.source_operation_id:
        raise NativeExtendError(EXTEND_PARENT_MEDIA_ID_MISSING, "source_operation_id")
    if not req.blocks:
        raise NativeExtendError(EXTEND_RUNTIME_CONTRACT_MISSING, "no extend blocks")
    model_key = config.EXTEND_VIDEO_MODELS.get(req.aspect_ratio)
    if not model_key:
        raise NativeExtendError(EXTEND_UNSUPPORTED_MODEL, req.aspect_ratio)
    return model_key


async def plan_native_extend_chain(req: ExtendChainRequest) -> dict:
    """Resume-aware plan (no side effects, no submit). For each block, resolve its
    expected PARENT (prior block's persisted child if already SUCCEEDED, else the
    source chain) and whether it still needs a live submission. Once a block is not
    yet succeeded, downstream parents are unknown until it fires, so those blocks
    also need submission. ``planned_operation_count`` is the exact number of
    credit-consuming submits a live run would perform — the number the operator must
    explicitly confirm."""
    model_key = _validate_context(req)
    steps: list[dict] = []
    parent = req.source_operation_id
    parent_known = True
    for block in req.blocks:
        prompt_hash = _prompt_hash(block.prompt)
        idem = (_idempotency_key(req.project_id, req.scene_id, block.position,
                                 prompt_hash, parent) if parent_known else None)
        existing = await _crud.get_extend_lineage_by_idempotency(idem) if idem else None
        succeeded = bool(existing
                         and existing.get("polling_state") == STATE_SUCCEEDED
                         and existing.get("child_operation_id"))
        steps.append({
            "block_index": block.block_index,
            "position": block.position,
            "parent_operation_id": parent if parent_known else None,
            "idempotency_key": idem,
            "existing_state": existing.get("polling_state") if existing else None,
            "needs_submit": not succeeded,
            "endpoint": config.ENDPOINTS["generate_video_extend"],
            "videoModelKey": model_key,
            "aspect_ratio": req.aspect_ratio,
            "videoInput": {"mediaId": parent if parent_known else None,
                           "startFrameIndex": block.start_frame_index,
                           "endFrameIndex": block.end_frame_index},
        })
        if succeeded:
            parent = existing["child_operation_id"]  # known chain continues
        else:
            parent_known = False
            parent = None
    return {
        "model_key": model_key,
        "block_count": len(req.blocks),
        "planned_operation_count": sum(1 for s in steps if s["needs_submit"]),
        "steps": steps,
    }


# ── Orchestrator ────────────────────────────────────────────────────────────
async def run_native_extend_chain(
    client,
    req: ExtendChainRequest,
    *,
    dry_run: bool = True,
    confirm_live_credit_burn: bool = False,
    confirmed_extend_operation_count: Optional[int] = None,
    poll_timeout_s: int = 600,
    poll_interval_s: int = 5,
) -> dict:
    """THE single authoritative native-extend execution path.

    Explicit live/dry-run contract — caller intent is NEVER silently rewritten:
      * ``dry_run=True``  -> plan + persist SOURCE_READY, fire nothing.
      * ``dry_run=False`` + no confirm            -> LIVE_CREDIT_CONFIRMATION_REQUIRED.
      * ``dry_run=False`` + confirm + flag OFF     -> NATIVE_EXTEND_DISABLED.
      * ``dry_run=False`` + confirm + no count     -> LIVE_CREDIT_CONFIRMATION_REQUIRED.
      * ``dry_run=False`` + confirm + count != plan-> EXTEND_CONFIRMATION_COUNT_MISMATCH.
      * ``dry_run=False`` + confirm + flag ON + count==plan -> LIVE execution.

    ``confirmed_extend_operation_count`` is the BOUNDED credit authorization: it must
    equal the resume-aware number of credit-consuming submits the live run will make,
    so a caller can never accidentally authorize more blocks than it saw.
    """
    _routes.require_capability("GOOGLE_FLOW_NATIVE_EXTEND_REQUEST")
    plan = await plan_native_extend_chain(req)  # validates context + resolves plan
    planned_operation_count = plan["planned_operation_count"]

    base = {
        "project_id": req.project_id,
        "scene_id": req.scene_id,
        "source_operation_id": req.source_operation_id,
        "planned_operation_count": planned_operation_count,
        "block_count": plan["block_count"],
        "model_key": plan["model_key"],
        "plan": plan["steps"],
    }

    if dry_run:
        results = await _persist_dry_run_plan(req, plan)
        return {**base, "dry_run": True, "blocks": results}

    # ── LIVE intent — explicit, fail-closed, bounded ──
    if not confirm_live_credit_burn:
        raise NativeExtendError(LIVE_CREDIT_CONFIRMATION_REQUIRED,
                                "confirm_live_credit_burn required for dry_run=false")
    if not native_extend_enabled():
        raise NativeExtendError(NATIVE_EXTEND_DISABLED, "NATIVE_EXTEND_ENABLED!=1")
    if confirmed_extend_operation_count is None:
        raise NativeExtendError(LIVE_CREDIT_CONFIRMATION_REQUIRED,
                                "confirmed_extend_operation_count required for live run")
    if int(confirmed_extend_operation_count) != planned_operation_count:
        raise NativeExtendError(
            EXTEND_CONFIRMATION_COUNT_MISMATCH,
            f"confirmed={confirmed_extend_operation_count} planned={planned_operation_count}")

    results: list[dict] = []
    parent_op = req.source_operation_id
    for block in req.blocks:
        outcome = await _run_one_extend_block(
            client, req, block, parent_op,
            poll_timeout_s=poll_timeout_s, poll_interval_s=poll_interval_s,
        )
        results.append(outcome)
        child = outcome.get("child_operation_id")
        if child:
            parent_op = child  # chain: next block extends this child
        else:
            break  # live run produced no child — stop the chain, fail closed

    return {
        **base, "dry_run": False, "blocks": results,
        "chain": [req.source_operation_id]
        + [b.get("child_operation_id") for b in results if b.get("child_operation_id")],
    }


async def _persist_dry_run_plan(req: ExtendChainRequest, plan: dict) -> list[dict]:
    """Persist SOURCE_READY lineage for planned-and-known blocks (idempotent), and
    return the per-block dry-run outcome. Blocks whose parent is unknown until an
    earlier block fires are reported without a lineage row (parent is None)."""
    outcomes: list[dict] = []
    for step, block in zip(plan["steps"], req.blocks):
        state = step["existing_state"]
        lineage_id = None
        if step["parent_operation_id"] and step["needs_submit"]:
            existing = await _crud.get_extend_lineage_by_idempotency(step["idempotency_key"])
            if existing:
                lineage_id = existing["extend_lineage_id"]
                state = existing["polling_state"]
            else:
                lineage_id = str(uuid.uuid4())
                await _crud.insert_extend_lineage(
                    lineage_id,
                    workspace_generation_package_id=req.workspace_generation_package_id,
                    project_id=req.project_id, scene_id=req.scene_id,
                    block_index=block.block_index, block_position=block.position,
                    parent_operation_id=step["parent_operation_id"],
                    model_key=plan["model_key"], aspect_ratio=req.aspect_ratio,
                    start_frame_index=block.start_frame_index,
                    end_frame_index=block.end_frame_index,
                    continuation_prompt_hash=_prompt_hash(block.prompt),
                    idempotency_key=step["idempotency_key"],
                    polling_state=STATE_SOURCE_READY,
                )
                state = STATE_SOURCE_READY
        outcomes.append({
            "lineage_id": lineage_id, "block_index": block.block_index,
            "position": block.position, "dry_run": True,
            "parent_operation_id": step["parent_operation_id"],
            "child_operation_id": None, "needs_submit": step["needs_submit"],
            "planned_request": {"endpoint": step["endpoint"],
                                "videoModelKey": step["videoModelKey"],
                                "videoInput": step["videoInput"],
                                "sceneContext": {"sceneId": req.scene_id,
                                                 "position": block.position}},
            "polling_state": state or STATE_SOURCE_READY,
        })
    return outcomes


async def _run_one_extend_block(
    client, req: ExtendChainRequest, block: ExtendBlock, parent_op: str,
    *, poll_timeout_s: int, poll_interval_s: int,
) -> dict:
    """Execute ONE live extend block. Reached only after run_native_extend_chain has
    passed every gate (capability + kill-switch + confirm + bounded count)."""
    if not parent_op:
        raise NativeExtendError(EXTEND_PARENT_MEDIA_ID_MISSING, f"block{block.block_index}")

    prompt_hash = _prompt_hash(block.prompt)
    idem = _idempotency_key(req.project_id, req.scene_id, block.position, prompt_hash, parent_op)
    model_key = config.EXTEND_VIDEO_MODELS.get(req.aspect_ratio)
    if not model_key:
        raise NativeExtendError(EXTEND_UNSUPPORTED_MODEL, req.aspect_ratio)

    existing = await _crud.get_extend_lineage_by_idempotency(idem)
    if existing:
        state = existing.get("polling_state")
        if state == STATE_SUCCEEDED and existing.get("child_operation_id"):
            return _lineage_outcome(existing, resumed=True)  # resume: never re-submit
        if state in (STATE_SUBMITTED, STATE_POLLING):
            # in-flight OR crashed after a prior submit — fail closed, never double-spend
            raise NativeExtendError(EXTEND_DUPLICATE_SUBMISSION_BLOCKED, idem)

    lineage_id = existing["extend_lineage_id"] if existing else str(uuid.uuid4())
    if not existing:
        await _crud.insert_extend_lineage(
            lineage_id,
            workspace_generation_package_id=req.workspace_generation_package_id,
            project_id=req.project_id, scene_id=req.scene_id,
            block_index=block.block_index, block_position=block.position,
            parent_operation_id=parent_op, model_key=model_key,
            aspect_ratio=req.aspect_ratio,
            start_frame_index=block.start_frame_index,
            end_frame_index=block.end_frame_index,
            continuation_prompt_hash=prompt_hash, idempotency_key=idem,
            polling_state=STATE_SOURCE_READY,
        )
    else:
        # retry of a prior FAILED / SOURCE_READY / BLOCKED row (same parent, same idem)
        await _crud.update_extend_lineage(
            lineage_id, parent_operation_id=parent_op,
            polling_state=STATE_SOURCE_READY, error_code=None, error_message=None,
            retry_attempt=(existing.get("retry_attempt") or 0) + 1,
        )

    # DEFECT-8 fix: mark EXTEND_SUBMITTED *before* the network call. If the process
    # dies during/after submit, the row is EXTEND_SUBMITTED (no child) and a later
    # resume fails closed (EXTEND_DUPLICATE_SUBMISSION_BLOCKED) instead of double-spending.
    await _crud.update_extend_lineage(lineage_id, polling_state=STATE_SUBMITTED)

    # ── LIVE SUBMIT ─────────────────────────────────────────────────────────
    resp = await client.generate_video_extend(
        source_operation_id=parent_op, project_id=req.project_id, scene_id=req.scene_id,
        position=block.position, prompt=block.prompt, aspect_ratio=req.aspect_ratio,
        start_frame_index=block.start_frame_index, end_frame_index=block.end_frame_index,
        seed=req.seed, user_paygate_tier=req.user_paygate_tier,
    )
    if not resp or resp.get("error"):
        # a REJECTED submit spends no credit -> FAILED (retryable on resume)
        detail = str(resp.get("error")) if resp else "no response"
        await _crud.update_extend_lineage(lineage_id, polling_state=STATE_FAILED,
                                          error_code=EXTEND_REQUEST_REJECTED,
                                          error_message=detail)
        raise NativeExtendError(EXTEND_REQUEST_REJECTED, detail)

    child = extract_extend_child(resp)
    if not child or not child.get("child_operation_id"):
        await _crud.update_extend_lineage(lineage_id, polling_state=STATE_FAILED,
                                          error_code=EXTEND_CHILD_MEDIA_ID_MISSING)
        raise NativeExtendError(EXTEND_CHILD_MEDIA_ID_MISSING)
    if child["child_operation_id"] == parent_op:
        await _crud.update_extend_lineage(lineage_id, polling_state=STATE_FAILED,
                                          error_code=EXTEND_LINEAGE_MISMATCH)
        raise NativeExtendError(EXTEND_LINEAGE_MISMATCH,
                                "child == parent operation id")

    await _crud.update_extend_lineage(
        lineage_id,
        child_operation_id=child["child_operation_id"],
        child_primary_media_id=child["child_primary_media_id"],
        child_workflow_id=child["child_workflow_id"], batch_id=child.get("batch_id"),
    )

    _routes.require_capability("GOOGLE_FLOW_EXTEND_CHILD_POLLING")
    status = await _poll_child(client, req.project_id, child["child_operation_id"],
                               lineage_id, poll_timeout_s=poll_timeout_s,
                               poll_interval_s=poll_interval_s)
    if status is None:
        await _crud.update_extend_lineage(lineage_id, polling_state=STATE_POLLING,
                                          error_code=EXTEND_OPERATION_TIMEOUT)
        raise NativeExtendError(EXTEND_OPERATION_TIMEOUT, child["child_operation_id"])
    if status == TERMINAL_FAILED:
        await _crud.update_extend_lineage(lineage_id, polling_state=STATE_FAILED,
                                          error_code=EXTEND_OPERATION_FAILED,
                                          completed_at=_crud._now())
        raise NativeExtendError(EXTEND_OPERATION_FAILED, child["child_operation_id"])

    # ── RETRIEVE ────────────────────────────────────────────────────────────
    _routes.require_capability("GOOGLE_FLOW_PER_BLOCK_MEDIA_RETRIEVAL")
    output_url = None
    try:
        media = await client.get_media(child["child_operation_id"])
        output_url = _extract_media_url(media)
    except Exception as exc:  # harvest is best-effort; keep the proven child id
        logger.warning("extend harvest failed for %s: %s",
                       child["child_operation_id"], exc)
        await _crud.update_extend_lineage(lineage_id, polling_state=STATE_HARVEST_FAILED,
                                          error_code="HARVEST_FAILED",
                                          error_message=str(exc))

    _routes.require_capability("GOOGLE_FLOW_EXTEND_LINEAGE")
    await _crud.update_extend_lineage(lineage_id, polling_state=STATE_SUCCEEDED,
                                      output_url=output_url, completed_at=_crud._now())
    return {
        "lineage_id": lineage_id, "block_index": block.block_index,
        "position": block.position, "dry_run": False,
        "parent_operation_id": parent_op,
        "child_operation_id": child["child_operation_id"],
        "child_primary_media_id": child["child_primary_media_id"],
        "child_workflow_id": child["child_workflow_id"],
        "output_url": output_url, "polling_state": STATE_SUCCEEDED,
    }


async def _poll_child(client, project_id: str, child_op: str, lineage_id: str,
                      *, poll_timeout_s: int, poll_interval_s: int) -> Optional[str]:
    await _crud.update_extend_lineage(lineage_id, polling_state=STATE_POLLING)
    elapsed = 0
    while elapsed <= poll_timeout_s:
        resp = await client.check_video_status_by_media(
            [{"name": child_op, "projectId": project_id}])
        status = _status_from_poll(resp, child_op)
        if status in (TERMINAL_SUCCESS, TERMINAL_FAILED):
            return status
        if poll_interval_s <= 0:
            break
        await asyncio.sleep(poll_interval_s)
        elapsed += poll_interval_s
    return None


def _lineage_outcome(row: dict, *, resumed: bool = False) -> dict:
    return {
        "lineage_id": row.get("extend_lineage_id"),
        "block_index": row.get("block_index"),
        "position": row.get("block_position"),
        "parent_operation_id": row.get("parent_operation_id"),
        "child_operation_id": row.get("child_operation_id"),
        "child_primary_media_id": row.get("child_primary_media_id"),
        "output_url": row.get("output_url"),
        "polling_state": row.get("polling_state"),
        "resumed": resumed,
        "dry_run": False,
    }


def final_concat_export_status() -> dict:
    """The 16s combined concatenated export is fail-closed. Callers that want a
    combined deliverable must surface this — NEVER substitute the Download Project
    ZIP (which is block1.mp4 + a poster image, not the continuation)."""
    return {
        "capability": "GOOGLE_FLOW_FINAL_CONCAT_EXPORT",
        "authority": _routes.AUTHORITY_MISSING,
        "error_code": FINAL_CONCAT_EXPORT_AUTHORITY_MISSING,
    }
