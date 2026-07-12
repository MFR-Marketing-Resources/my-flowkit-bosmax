"""Owner-approved CURRENT-UI video driver (Phase 2B — three blocker closure).

Composer-scoped reference gate, exact parent media operation id selection,
Extend submit → poll → correlate → persist → sequential lineage.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
import zipfile
from pathlib import Path
from typing import Optional

from agent.db import crud

# ── states (Owner Phase-2 contract) ──────────────────────────────────────────
S_COMPOSER_READY = "COMPOSER_READY"
S_STALE_REFERENCES_CHECKING = "STALE_REFERENCES_CHECKING"
S_STALE_REFERENCES_CLEARED = "STALE_REFERENCES_CLEARED_OR_ZERO"
S_REFERENCES_ATTACHING = "REFERENCES_ATTACHING"
S_REFERENCES_VISIBLE = "REFERENCES_VISIBLE"
S_REFERENCE_COUNT_CONFIRMED = "REFERENCE_COUNT_CONFIRMED"
S_REFERENCE_ORDER_CONFIRMED = "REFERENCE_ORDER_CONFIRMED"
S_BLOCK1_PROMPT_INSERTING = "BLOCK1_PROMPT_INSERTING"
S_BLOCK1_PROMPT_CONFIRMED = "BLOCK1_PROMPT_CONFIRMED"
S_SETTINGS_APPLYING = "SETTINGS_APPLYING"
S_SETTINGS_CONFIRMED = "SETTINGS_CONFIRMED"
S_READY_FOR_NEGOTIATION = "READY_FOR_NEGOTIATION"

S_CURRENT_VIDEO_OPENING = "CURRENT_VIDEO_OPENING"
S_CURRENT_VIDEO_CONFIRMED = "CURRENT_VIDEO_CONFIRMED"
S_EXTEND_CONTROL_OPENING = "EXTEND_CONTROL_OPENING"
S_EXTEND_PROMPT_READY = "EXTEND_PROMPT_READY"
S_NEXT_BLOCK_PROMPT_CONFIRMED = "NEXT_BLOCK_PROMPT_CONFIRMED"
S_EXTEND_READY_TO_SUBMIT = "EXTEND_READY_TO_SUBMIT"
S_EXTEND_SUBMITTED = "EXTEND_SUBMITTED"
S_EXTEND_POLLING = "EXTEND_POLLING"
S_CHILD_CANDIDATE_FOUND = "CHILD_CANDIDATE_FOUND"
S_CHILD_IDENTITY_CONFIRMED = "CHILD_IDENTITY_CONFIRMED"
S_CHILD_PERSISTED = "CHILD_PERSISTED"
S_EXTEND_COMPLETE = "EXTEND_COMPLETE"
S_NEXT_BLOCK_READY = "NEXT_BLOCK_READY"

S_DOWNLOAD_COMPLETED = "DOWNLOAD_COMPLETED"
S_ARTIFACT_REGISTERED = "ARTIFACT_REGISTERED"

ERR_DISABLED = "FLOW_UI_DRIVER_DISABLED"
ERR_CONFIRM = "LIVE_CREDIT_CONFIRMATION_REQUIRED"
ERR_ROUTE_LOCKED = "EXTEND_ROUTE_ALREADY_SUBMITTED"
ERR_REFERENCES_NOT_VISIBLE = "REFERENCES_NOT_VISIBLE"
ERR_STALE_REFERENCES = "STALE_REFERENCES_PRESENT"
ERR_MULTI_BLOCK_PROMPT = "EXTEND_PROMPT_MULTI_BLOCK_REJECTED"
ERR_DOWNLOAD_INCOMPLETE = "DOWNLOAD_INCOMPLETE"
ERR_COMPOSER_ATTACH_FAILED = "COMPOSER_ATTACH_FAILED"

ERR_CURRENT_VIDEO_NOT_FOUND = "CURRENT_VIDEO_NOT_FOUND"
ERR_CURRENT_VIDEO_IDENTITY_MISMATCH = "CURRENT_VIDEO_IDENTITY_MISMATCH"
ERR_CURRENT_VIDEO_PROJECT_MISMATCH = "CURRENT_VIDEO_PROJECT_MISMATCH"

ERR_EXTEND_CHILD_NOT_FOUND = "EXTEND_CHILD_NOT_FOUND"
ERR_EXTEND_CHILD_PROMPT_MISMATCH = "EXTEND_CHILD_PROMPT_MISMATCH"
ERR_EXTEND_UNCERTAIN = "EXTEND_SUBMIT_UNCERTAIN"

_BLOCK_HEADER_MARKER = "SECTION 1 - ROLE & OBJECTIVE"


class FlowUiDriverError(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


def ui_driver_enabled() -> bool:
    return os.environ.get("FLOW_UI_DRIVER_ENABLED") == "1"


def _res(envelope: dict) -> dict:
    if not isinstance(envelope, dict):
        return {"ok": False, "error": "FLOWUI_BAD_ENVELOPE"}
    return envelope.get("result", envelope)


def _map_open_video_error(err: str) -> str:
    if err == "CURRENT_VIDEO_NOT_FOUND":
        return ERR_CURRENT_VIDEO_NOT_FOUND
    if err == "CURRENT_VIDEO_IDENTITY_MISMATCH":
        return ERR_CURRENT_VIDEO_IDENTITY_MISMATCH
    if err == "CURRENT_VIDEO_PROJECT_MISMATCH":
        return ERR_CURRENT_VIDEO_PROJECT_MISMATCH
    return err or ERR_CURRENT_VIDEO_NOT_FOUND


# ── composer reference gate (Blocker 1) ────────────────────────────────────
async def ensure_composer_references(
    client,
    *,
    media_ids: list,
    local_file_paths: list,
    expected_count: int,
) -> dict:
    """Attach references to the real composer and verify scoped thumbnails."""
    ids = [str(m) for m in (media_ids or []) if m]
    paths = [str(p) for p in (local_file_paths or []) if p]
    states: list = []

    def mark(state: str, **kw):
        states.append({"state": state, **kw})

    mark(S_COMPOSER_READY)
    mark(S_STALE_REFERENCES_CHECKING)
    if expected_count == 0:
        zero = _res(await client.flowui_verify_composer_zero())
        if not zero.get("ok"):
            raise FlowUiDriverError(
                ERR_STALE_REFERENCES,
                str(zero.get("error") or zero.get("detail") or zero))
        mark(S_STALE_REFERENCES_CLEARED, count=0)
        return {"ok": True, "expected_count": 0, "states": states}

    if len(ids) != expected_count:
        raise FlowUiDriverError(
            ERR_REFERENCES_NOT_VISIBLE,
            f"reference list count {len(ids)} != mode contract {expected_count}")

    mark(S_REFERENCES_ATTACHING)
    if paths:
        if len(paths) != expected_count:
            raise FlowUiDriverError(
                ERR_COMPOSER_ATTACH_FAILED,
                f"local paths {len(paths)} != expected {expected_count}")
        for i, path in enumerate(paths):
            attached = _res(await client.flowui_composer_attach_file(
                path, slot_label=f"ComposerRef{i + 1}"))
            if not attached.get("ok"):
                raise FlowUiDriverError(
                    ERR_COMPOSER_ATTACH_FAILED, str(attached.get("error")))

    vis = _res(await client.flowui_verify_media_visible(ids))
    if not vis.get("ok"):
        raise FlowUiDriverError(
            ERR_REFERENCES_NOT_VISIBLE,
            f"missing={vis.get('missing')} unexpected={vis.get('unexpected_ids')} "
            f"duplicates={vis.get('duplicate_ids')} "
            f"actual_total={vis.get('actual_total_count')} expected={expected_count}")
    if vis.get("actual_total_count") != expected_count:
        raise FlowUiDriverError(
            ERR_REFERENCES_NOT_VISIBLE,
            f"composer actual_total_count={vis.get('actual_total_count')} "
            f"!= expected {expected_count}")
    if vis.get("unexpected_ids"):
        raise FlowUiDriverError(
            ERR_REFERENCES_NOT_VISIBLE,
            f"unexpected composer thumbnails: {vis.get('unexpected_ids')}")
    mark(S_REFERENCES_VISIBLE, visible_count=vis.get("visible_count"))
    mark(S_REFERENCE_COUNT_CONFIRMED, count=expected_count)
    if expected_count > 1 and vis.get("order_ok") is False:
        raise FlowUiDriverError(ERR_REFERENCES_NOT_VISIBLE, "reference order mismatch")
    mark(S_REFERENCE_ORDER_CONFIRMED)
    return {"ok": True, "states": states, **vis}


async def verify_references_visible(client, media_ids: list,
                                    expected_count: int) -> dict:
    """Composer-scoped visibility gate (T2V uses expected_count=0)."""
    if expected_count == 0:
        zero = _res(await client.flowui_verify_composer_zero())
        if not zero.get("ok"):
            raise FlowUiDriverError(ERR_STALE_REFERENCES, str(zero.get("error")))
        return {"ok": True, "expected_count": 0, "visible_count": 0,
                "scope": "composer_reference_container"}
    return await ensure_composer_references(
        client, media_ids=media_ids, local_file_paths=[], expected_count=expected_count)


async def run_initial_block1_via_composer(
    client,
    *,
    prompt: str,
    media_ids: list,
    local_file_paths: list,
    expected_count: int,
    dry_run: bool = True,
    confirm_live_credit_burn: bool = False,
    request_id: str | None = None,
    intercept_submit: bool = False,
) -> dict:
    """Composer-driven Block 1 initial lane (mutually exclusive with API initial)."""
    states: list = []

    def mark(state: str, **kw):
        states.append({"state": state, **kw})

    ref_out = await ensure_composer_references(
        client, media_ids=media_ids, local_file_paths=local_file_paths,
        expected_count=expected_count)
    states.extend(ref_out.get("states") or [])

    mark(S_BLOCK1_PROMPT_INSERTING)
    typed = _res(await client.flowui_set_composer_prompt(prompt))
    if not typed.get("ok"):
        raise FlowUiDriverError("BLOCK1_PROMPT_INSERT_FAILED",
                                str(typed.get("error")))
    mark(S_BLOCK1_PROMPT_CONFIRMED, length=typed.get("length"))
    mark(S_SETTINGS_APPLYING)
    mark(S_SETTINGS_CONFIRMED, note="composer_surface_authority")
    mark(S_READY_FOR_NEGOTIATION)

    idem = (
        f"UI_INITIAL:{request_id or 'manual'}:"
        f"{hashlib.sha256((prompt or '').encode()).hexdigest()[:16]}"
    )

    if dry_run:
        boundary = _res(await client.flowui_submit_composer_create(
            confirm=True, intercept_only=True))
        return {
            "ok": True,
            "dry_run": True,
            "lane": "UI_COMPOSER_INITIAL",
            "states": states,
            "submit_boundary": boundary,
            "idempotency_key": idem,
            "idempotency_would_reserve": True,
        }

    if not ui_driver_enabled():
        raise FlowUiDriverError(ERR_DISABLED, "FLOW_UI_DRIVER_ENABLED != 1")
    if confirm_live_credit_burn is not True:
        raise FlowUiDriverError(ERR_CONFIRM,
                                "explicit confirm_live_credit_burn required")

    reserve = await crud.reserve_video_job_side_effect(
        idem, job_id=request_id or idem, stage="INITIAL")
    if not reserve.get("reserved"):
        raise FlowUiDriverError(
            "INITIAL_SUBMIT_BLOCKED",
            f"duplicate initial submit (state={reserve.get('row', {}).get('submission_state')})")

    sub = _res(await client.flowui_submit_composer_create(
        confirm=True, intercept_only=bool(intercept_submit)))
    if not sub.get("ok"):
        await crud.update_video_job_side_effect(
            idem, submission_state="NOT_ATTEMPTED", retry_safety="SAFE",
            detail=str(sub.get("error")))
        raise FlowUiDriverError("INITIAL_SUBMIT_FAILED", str(sub.get("error")))

    mark("INITIAL_SUBMIT_INVOKED", intercept_only=intercept_submit)
    return {
        "ok": True,
        "lane": "UI_COMPOSER_INITIAL",
        "states": states,
        "submit_result": sub,
        "idempotency_key": idem,
    }


# ── typed timeline snapshot for UI Extend polling ─────────────────────────────
def _typed_timeline_snapshot(resp: dict) -> dict:
    data = resp.get("data", resp) if isinstance(resp, dict) else {}
    if not isinstance(data, dict):
        data = {}
    media_resource_ids: set = set()
    workflow_ids: set = set()
    primary_media_ids: set = set()
    records: list = []
    for m in data.get("media") or []:
        if not isinstance(m, dict):
            continue
        mr = m.get("name")
        wf = m.get("workflowId")
        sid = m.get("sceneId")
        rec = {
            "media_resource_id": str(mr) if mr else None,
            "workflow_id": str(wf) if wf else None,
            "primary_media_id": None,
            "operation_id": None,
            "scene_id": str(sid) if sid else None,
            "project_id": m.get("projectId"),
        }
        records.append(rec)
        if mr:
            media_resource_ids.add(str(mr))
        if wf:
            workflow_ids.add(str(wf))
    for sw in data.get("sceneWorkflows") or []:
        if not isinstance(sw, dict):
            continue
        wf = sw.get("workflow") or {}
        if not isinstance(wf, dict):
            continue
        meta = wf.get("metadata") or {}
        wname = wf.get("name")
        pmid = meta.get("primaryMediaId") if isinstance(meta, dict) else None
        records.append({
            "media_resource_id": None,
            "workflow_id": str(wname) if wname else None,
            "primary_media_id": str(pmid) if pmid else None,
            "operation_id": None,
            "scene_id": sw.get("sceneId"),
            "project_id": None,
        })
        if wname:
            workflow_ids.add(str(wname))
        if pmid:
            primary_media_ids.add(str(pmid))
    return {
        "records": records,
        "media_resource_ids": media_resource_ids,
        "workflow_ids": workflow_ids,
        "primary_media_ids": primary_media_ids,
        "operation_ids": set(),
    }


async def _snapshot_timeline_media(client, project_id: str, scene_id: str) -> dict:
    if not project_id or not scene_id:
        raise FlowUiDriverError("EXTEND_PROJECT_CONTEXT_MISSING",
                                "project_id and scene_id required for UI polling")
    resp = await client.list_scene_workflows(scene_id, project_id)
    return _typed_timeline_snapshot(resp)


async def _correlate_ui_extend_child(
    client, *, project_id: str, candidates: list, submitted_prompt: str,
    snapshot: dict, model_key: str | None = None, seed=None,
) -> dict | None:
    from agent.services.make_video import _extract_provider_prompt

    prior_media = snapshot.get("media_resource_ids") or set()
    for mid in candidates:
        if mid in prior_media:
            continue
        media = await client.get_media(mid)
        mdata = media.get("data", media) if isinstance(media, dict) else media
        if not isinstance(mdata, dict):
            continue
        video_meta = mdata.get("video") if isinstance(mdata.get("video"), dict) else {}
        norm_path, vprompt = _extract_provider_prompt(video_meta.get("prompt"))
        if vprompt is None or vprompt.strip() != submitted_prompt.strip():
            continue
        vmodel = video_meta.get("model")
        if model_key and vmodel and str(vmodel) != str(model_key):
            continue
        vseed = video_meta.get("seed")
        if seed is not None and vseed is not None and str(vseed) != str(seed):
            continue
        child_media_id = str(mdata.get("name") or mid)
        return {
            "child_media_id": child_media_id,
            "child_primary_media_id": (
                video_meta.get("primaryMediaId")
                or mdata.get("primaryMediaId")
            ),
            "child_workflow_id": mdata.get("workflowId"),
            "child_operation_id": None,
            "correlation_evidence": {
                "normalization_path": norm_path,
                "prompt_match": True,
                "model": vmodel,
                "seed": vseed,
                "identity_types": {
                    "media_resource_id": child_media_id,
                    "operation_id": None,
                },
            },
        }
    return None


async def _poll_ui_extend_child(
    client, *, project_id: str, scene_id: str, submitted_prompt: str,
    snapshot: dict, poll_timeout_s: int = 120, poll_interval_s: int = 5,
    model_key: str | None = None, seed=None,
) -> dict:
    prior_media = snapshot.get("media_resource_ids") or set()
    elapsed = 0
    while elapsed <= poll_timeout_s:
        current = await _snapshot_timeline_media(client, project_id, scene_id)
        new_ids = [
            m for m in current.get("media_resource_ids") or set()
            if m not in prior_media
        ]
        child = await _correlate_ui_extend_child(
            client, project_id=project_id, candidates=new_ids,
            submitted_prompt=submitted_prompt, snapshot=snapshot,
            model_key=model_key, seed=seed)
        if child:
            return child
        await asyncio.sleep(poll_interval_s)
        elapsed += poll_interval_s
    raise FlowUiDriverError(ERR_EXTEND_CHILD_NOT_FOUND, "polling exhausted")


def _ui_parent_media_resource_id(job: dict) -> str | None:
    state = json.loads(job.get("stage_state_json") or "{}")
    chain = state.get("ui_parent_media_resource_ids") or []
    if chain:
        return str(chain[-1])
    im = job.get("initial_media_id")
    return str(im) if im else None


async def _persist_ui_extend_child(
    job: dict, *, block_index: int, position: int, parent_op: str,
    child: dict, prompt: str, idem: str, workspace_generation_package_id: str | None,
) -> str:
    from agent.services import google_flow_native_extend_runtime as _nx

    child_media = child.get("child_media_id")
    child_op = child.get("child_operation_id")
    child_pmid = child.get("child_primary_media_id")

    existing = await crud.get_extend_lineage_by_idempotency(idem)
    lineage_id = existing["extend_lineage_id"] if existing else str(uuid.uuid4())
    if not existing:
        await crud.insert_extend_lineage(
            lineage_id,
            workspace_generation_package_id=workspace_generation_package_id,
            project_id=job.get("project_id"),
            scene_id=job.get("scene_id"),
            block_index=block_index,
            block_position=position,
            parent_operation_id=parent_op,
            child_operation_id=child_op,
            child_primary_media_id=child_pmid,
            continuation_prompt_hash=_nx._prompt_hash(prompt),
            idempotency_key=idem,
            polling_state="EXTEND_SUCCEEDED",
        )
    else:
        await crud.update_extend_lineage(
            lineage_id,
            child_operation_id=child_op,
            child_primary_media_id=child_pmid,
            polling_state="EXTEND_SUCCEEDED",
        )

    job_id = job["job_id"]
    segments = json.loads(job.get("segment_media_ids_json") or "[]")
    if child_op and child_op not in segments:
        segments.append(child_op)

    state = json.loads(job.get("stage_state_json") or "{}")
    ui_chain = list(state.get("ui_parent_media_resource_ids") or [])
    if not ui_chain and job.get("initial_media_id"):
        ui_chain.append(str(job["initial_media_id"]))
    if child_media:
        ui_chain.append(str(child_media))
    state["ui_parent_media_resource_ids"] = ui_chain

    await crud.update_video_production_job_full(
        job_id,
        segment_media_ids_json=json.dumps(segments),
        extend_child_operation_id=child_op,
        extend_child_workflow_id=child.get("child_workflow_id"),
        stage_state_json=json.dumps(state),
    )
    return lineage_id


# ── timeline Extend for ONE block (Blocker 2 + 3) ───────────────────────────
async def extend_block_via_ui(
    client, *, job_id: str, parent_media_operation_id: str = "",
    parent_media_resource_id: str = "",
    block_index: int, position: int, prompt: str,
    model_label: str = "Veo 3.1 - Lite",
    confirm_live_credit_burn: bool = False,
    dry_run: bool = True,
    poll_timeout_s: int = 120,
    poll_interval_s: int = 5,
) -> dict:
    if not prompt or (_BLOCK_HEADER_MARKER in prompt and prompt.count(_BLOCK_HEADER_MARKER) > 1):
        raise FlowUiDriverError(ERR_MULTI_BLOCK_PROMPT,
                                "extend prompt must be exactly ONE block")
    states: list = []

    def mark(state: str, **kw):
        states.append({"state": state, **kw})

    from agent.services import video_production_orchestrator as _orch
    from agent.services import google_flow_native_extend_runtime as _nx

    job = await crud.get_video_production_job(job_id)
    if not job:
        raise FlowUiDriverError("VIDEO_JOB_NOT_FOUND", job_id)
    segments = json.loads(job.get("segment_media_ids_json") or "[]")
    if not segments:
        raise FlowUiDriverError("EXTEND_PARENT_MISSING",
                                "job has no bound current Video 1")
    parent_op = segments[-1]
    open_id = (
        parent_media_resource_id
        or _ui_parent_media_resource_id(job)
        or parent_op
    )
    if parent_media_operation_id and parent_media_operation_id != parent_op:
        raise FlowUiDriverError(
            ERR_CURRENT_VIDEO_IDENTITY_MISMATCH,
            f"requested lineage parent {parent_media_operation_id} != {parent_op}")

    idem = _orch._stage_key(
        job, "EXTEND", f"{parent_op}|{_nx._prompt_hash(prompt)}|pos{position}")
    existing = await crud.get_video_job_side_effect(idem)
    if existing and existing.get("submission_state") != "NOT_ATTEMPTED":
        raise FlowUiDriverError(
            ERR_ROUTE_LOCKED,
            f"block pos{position} already submitted (state={existing.get('submission_state')})")

    project_id = job.get("project_id") or ""
    scene_id = job.get("scene_id") or ""
    snapshot: dict = {"media_resource_ids": set(), "workflow_ids": set()}
    if project_id and scene_id and not dry_run:
        snapshot = await _snapshot_timeline_media(client, project_id, scene_id)

    mark(S_CURRENT_VIDEO_OPENING, parent_operation_id=parent_op,
         parent_open_media_resource_id=open_id)
    opened = _res(await client.flowui_open_video(
        open_id, expected_project_id=project_id or None))
    if not opened.get("ok"):
        code = _map_open_video_error(str(opened.get("error")))
        raise FlowUiDriverError(code, str(opened.get("error")))
    mark(S_CURRENT_VIDEO_CONFIRMED, project_id=opened.get("project_id"))

    mark(S_EXTEND_CONTROL_OPENING)
    menu = _res(await client.flowui_add_clip_extend(model_label))
    if not menu.get("ok"):
        raise FlowUiDriverError("EXTEND_CONTROL_FAILED", str(menu.get("error")))
    mark(S_EXTEND_PROMPT_READY, menu_item=menu.get("menu_item"))

    typed = _res(await client.flowui_set_extend_prompt(prompt))
    if not typed.get("ok"):
        raise FlowUiDriverError("EXTEND_PROMPT_INSERT_FAILED",
                                str(typed.get("error")))
    read_back = str(typed.get("read_back") or "")
    if _BLOCK_HEADER_MARKER in read_back and read_back.count(_BLOCK_HEADER_MARKER) > 1:
        raise FlowUiDriverError(ERR_MULTI_BLOCK_PROMPT, "read-back shows >1 block")
    mark(S_NEXT_BLOCK_PROMPT_CONFIRMED, length=typed.get("length"))
    mark(S_EXTEND_READY_TO_SUBMIT, block_index=block_index, position=position)

    if dry_run:
        return {"ok": True, "dry_run": True, "states": states,
                "idempotency_key": idem, "parent_operation_id": parent_op}

    if not ui_driver_enabled():
        raise FlowUiDriverError(ERR_DISABLED, "FLOW_UI_DRIVER_ENABLED != 1")
    if confirm_live_credit_burn is not True:
        raise FlowUiDriverError(ERR_CONFIRM,
                                "explicit confirm_live_credit_burn required")

    reserve = await crud.reserve_video_job_side_effect(idem, job_id=job_id,
                                                       stage="EXTEND")
    if not reserve.get("reserved"):
        raise FlowUiDriverError(ERR_ROUTE_LOCKED,
                                "another route reserved this block first")

    await crud.update_video_job_side_effect(
        idem, submission_state="SUBMITTED", credit_state="MAY_HAVE_SPENT",
        retry_safety="RESUME_ONLY", detail="UI_TIMELINE_EXTEND")
    submitted = _res(await client.flowui_submit_extend(confirm=True))
    if not submitted.get("ok"):
        await crud.update_video_job_side_effect(
            idem, submission_state="UNCERTAIN", credit_state="MAY_HAVE_SPENT",
            retry_safety="BLOCKED", detail=str(submitted.get("error"))[:180])
        raise FlowUiDriverError(ERR_EXTEND_UNCERTAIN, str(submitted.get("error")))
    mark(S_EXTEND_SUBMITTED)

    mark(S_EXTEND_POLLING)
    try:
        child = await _poll_ui_extend_child(
            client, project_id=project_id, scene_id=scene_id,
            submitted_prompt=prompt, snapshot=snapshot,
            poll_timeout_s=poll_timeout_s, poll_interval_s=poll_interval_s,
            model_key=job.get("model"))
    except FlowUiDriverError:
        await crud.update_video_job_side_effect(
            idem, submission_state="UNCERTAIN", credit_state="MAY_HAVE_SPENT",
            retry_safety="BLOCKED", detail="UI_EXTEND_POLL_NO_CHILD")
        raise

    mark(S_CHILD_CANDIDATE_FOUND, child_media_id=child.get("child_media_id"),
         child_operation_id=child.get("child_operation_id"))
    mark(S_CHILD_IDENTITY_CONFIRMED, evidence=child.get("correlation_evidence"))

    job["job_id"] = job_id
    lineage_id = await _persist_ui_extend_child(
        job, block_index=block_index, position=position, parent_op=parent_op,
        child=child, prompt=prompt, idem=idem,
        workspace_generation_package_id=job.get("execution_package_id"))
    mark(S_CHILD_PERSISTED, lineage_id=lineage_id)
    mark(S_EXTEND_COMPLETE)
    mark(S_NEXT_BLOCK_READY, next_parent_media_resource_id=child.get("child_media_id"))

    op_ref = child.get("child_operation_id")
    await crud.update_video_job_side_effect(
        idem, submission_state="TERMINAL", credit_state="MAY_HAVE_SPENT",
        retry_safety="RESUME_ONLY", operation_ref=op_ref)

    return {
        "ok": True, "dry_run": False, "states": states,
        "idempotency_key": idem,
        "parent_operation_id": parent_op,
        "child_media_id": child.get("child_media_id"),
        "child_operation_id": child.get("child_operation_id"),
        "child_primary_media_id": child.get("child_primary_media_id"),
        "child_workflow_id": child.get("child_workflow_id"),
        "lineage_id": lineage_id,
    }


async def run_sequential_ui_extend_chain(
    client, *, job_id: str, blocks: list,
    confirm_live_credit_burn: bool = False,
    dry_run: bool = True,
) -> dict:
    """Block 2..N: each block uses the persisted child as the next parent."""
    results = []
    for block in sorted(blocks, key=lambda b: int(b.get("position") or 0)):
        out = await extend_block_via_ui(
            client,
            job_id=job_id,
            parent_media_operation_id="",  # lineage authority
            block_index=int(block["block_index"]),
            position=int(block["position"]),
            prompt=str(block["prompt"]),
            model_label=block.get("model_label") or "Veo 3.1 - Lite",
            confirm_live_credit_burn=confirm_live_credit_burn,
            dry_run=dry_run,
        )
        results.append(out)
        if not out.get("ok"):
            break
    return {"ok": all(r.get("ok") for r in results), "blocks": results}


async def assert_final_lineage_for_download(job_id: str) -> dict:
    job = await crud.get_video_production_job(job_id)
    if not job:
        raise FlowUiDriverError("VIDEO_JOB_NOT_FOUND", job_id)
    segments = json.loads(job.get("segment_media_ids_json") or "[]")
    if len(segments) < 2:
        raise FlowUiDriverError("FINAL_LINEAGE_INCOMPLETE",
                                "expected final child in segment lineage")
    final_child = segments[-1]
    parent = segments[-2] if len(segments) >= 2 else None
    return {
        "ok": True,
        "final_child_operation_id": final_child,
        "parent_operation_id": parent,
        "project_id": job.get("project_id"),
        "segment_count": len(segments),
    }


# ── Download Project (final-lineage gate) ───────────────────────────────────
async def download_project_via_ui(client, *, job_id: Optional[str],
                                  project_id: Optional[str],
                                  register: bool = True,
                                  require_final_lineage: bool = True) -> dict:
    if require_final_lineage and job_id:
        await assert_final_lineage_for_download(job_id)

    res = _res(await client.flowui_download_project())
    if not res.get("ok"):
        raise FlowUiDriverError("DOWNLOAD_PROJECT_FAILED", str(res.get("error")))
    dl = res.get("download") or {}
    local = str(dl.get("filename") or "")
    if dl.get("state") != "complete" or not local:
        raise FlowUiDriverError(ERR_DOWNLOAD_INCOMPLETE, json.dumps(dl)[:180])
    path = Path(local)
    if not path.exists():
        raise FlowUiDriverError(ERR_DOWNLOAD_INCOMPLETE,
                                f"browser reported complete but file missing: {local}")
    data = path.read_bytes()
    if not data:
        raise FlowUiDriverError(ERR_DOWNLOAD_INCOMPLETE, "0-byte download")
    sha = hashlib.sha256(data).hexdigest()
    is_zip = data[:4] == b"PK\x03\x04"
    entries: list = []
    if is_zip:
        try:
            with zipfile.ZipFile(path) as z:
                entries = z.namelist()[:50]
        except zipfile.BadZipFile:
            raise FlowUiDriverError(ERR_DOWNLOAD_INCOMPLETE,
                                    "zip signature present but archive unreadable")
    artifact_kind = "project_archive" if is_zip else "file"
    result = {
        "ok": True,
        "artifact_kind": artifact_kind,
        "local_path": str(path),
        "bytes": len(data),
        "sha256": sha,
        "mime": dl.get("mime"),
        "zip_entries": entries,
        "is_zip": is_zip,
        "job_id": job_id,
        "project_id": project_id,
        "state": S_DOWNLOAD_COMPLETED,
    }
    if register:
        artifact_id = f"project-archive:{sha[:24]}"
        registered = False
        vj = await crud.get_video_production_job(job_id) if job_id else None
        if vj is not None:
            try:
                state = json.loads(vj.get("stage_state_json") or "{}")
            except (TypeError, ValueError):
                state = {}
            archives = state.setdefault("project_archives", {})
            if artifact_id not in archives:
                archives[artifact_id] = {
                    "artifact_kind": artifact_kind, "local_path": str(path),
                    "bytes": len(data), "sha256": sha, "mime": dl.get("mime"),
                    "zip_entries": entries[:10], "project_id": project_id,
                    "final_child_operation_id": (
                        json.loads(vj.get("segment_media_ids_json") or "[]")[-1]
                        if vj.get("segment_media_ids_json") else None
                    ),
                }
                await crud.update_video_production_job_full(
                    job_id, stage_state_json=json.dumps(state))
            registered = True
        result["artifact_id"] = artifact_id
        result["registered"] = registered
        if not registered:
            result["registered_reason"] = "NO_DURABLE_JOB_ROW_FOR_JOB_ID"
        result["state"] = (S_ARTIFACT_REGISTERED if registered
                           else S_DOWNLOAD_COMPLETED)
    return result