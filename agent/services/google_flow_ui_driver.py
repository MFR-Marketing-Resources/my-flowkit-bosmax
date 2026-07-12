"""Owner-approved CURRENT-UI video driver (Phase 2 targeted refactor).

ONE shared driver for the Owner SOP path — never per-mode transports:

  reference visibility gate (pre-Block-1)
  → exact current Video 1 → open detail/timeline
  → Add Clip → "Extend (Veo 3.1 - Lite)" → Block-N prompt only
  → ONE submit per block (kill-switch + explicit confirm)
  → Download Project (browser download captured, hashed, inspected)
  → honest artifact registration (a ZIP is a project archive, never an MP4).

Selector authority: accessible names captured live 2026-07-12
(.ai/experiments/aisandbox_extend_discovery/out/ui_contract/*): "Add Clip",
"Extend ({{modelName}})", prompt box "What happens next?", toolbar "More",
menu item "Download Project". No generated CSS classes, no coordinates.

Safety contract:
  * kill switch: FLOW_UI_DRIVER_ENABLED must be "1" for ANY live UI submit;
  * route exclusivity: UI Extend and direct-RPC Extend share the SAME per-block
    idempotency stage key (video_job_side_effect) — a block that either route
    has already submitted can never be submitted again by the other;
  * the direct-RPC Native Extend implementation is untouched (protected
    fallback);
  * Download Project result is registered exactly as captured (zip signature +
    entry listing + sha256); an incomplete download is never a success.
"""
from __future__ import annotations

import hashlib
import json
import os
import zipfile
from pathlib import Path
from typing import Optional

from agent.db import crud

# ── states (Owner Phase-2 contract) ──────────────────────────────────────────
S_CURRENT_VIDEO_OPENING = "CURRENT_VIDEO_OPENING"
S_CURRENT_VIDEO_CONFIRMED = "CURRENT_VIDEO_CONFIRMED"
S_EXTEND_CONTROL_OPENING = "EXTEND_CONTROL_OPENING"
S_EXTEND_PROMPT_READY = "EXTEND_PROMPT_READY"
S_NEXT_BLOCK_PROMPT_CONFIRMED = "NEXT_BLOCK_PROMPT_CONFIRMED"
S_EXTEND_READY_TO_SUBMIT = "EXTEND_READY_TO_SUBMIT"
S_EXTEND_SUBMITTED = "EXTEND_SUBMITTED"
S_DOWNLOAD_COMPLETED = "DOWNLOAD_COMPLETED"
S_ARTIFACT_REGISTERED = "ARTIFACT_REGISTERED"

ERR_DISABLED = "FLOW_UI_DRIVER_DISABLED"
ERR_CONFIRM = "LIVE_CREDIT_CONFIRMATION_REQUIRED"
ERR_ROUTE_LOCKED = "EXTEND_ROUTE_ALREADY_SUBMITTED"
ERR_REFERENCES_NOT_VISIBLE = "REFERENCES_NOT_VISIBLE"
ERR_STALE_REFERENCES = "STALE_REFERENCES_PRESENT"
ERR_MULTI_BLOCK_PROMPT = "EXTEND_PROMPT_MULTI_BLOCK_REJECTED"
ERR_DOWNLOAD_INCOMPLETE = "DOWNLOAD_INCOMPLETE"

_BLOCK_HEADER_MARKER = "SECTION 1 - ROLE & OBJECTIVE"


class FlowUiDriverError(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


def ui_driver_enabled() -> bool:
    """Kill switch — default OFF: the proven API lane stays production authority
    until the Owner's controlled live test proves this driver."""
    return os.environ.get("FLOW_UI_DRIVER_ENABLED") == "1"


def _res(envelope: dict) -> dict:
    """Unwrap the WS relay envelope {result: {...}} → verb result."""
    if not isinstance(envelope, dict):
        return {"ok": False, "error": "FLOWUI_BAD_ENVELOPE"}
    return envelope.get("result", envelope)


# ── reference-first visibility gate (Boundary A) ─────────────────────────────
async def verify_references_visible(client, media_ids: list,
                                    expected_count: int) -> dict:
    """The Owner reference-first gate: every uploaded reference must be VISIBLY
    present in the current Flow project surface, and the visible count must
    equal the mode contract count, BEFORE Block-1 is sent. T2V passes
    expected_count=0 with an empty list (zero references, zero stale)."""
    ids = [str(m) for m in (media_ids or []) if m]
    if len(ids) != int(expected_count):
        raise FlowUiDriverError(
            ERR_REFERENCES_NOT_VISIBLE,
            f"reference list count {len(ids)} != mode contract {expected_count}")
    if not ids:  # T2V: nothing to verify visible; caller separately checks stale
        return {"ok": True, "expected_count": 0, "visible_count": 0}
    res = _res(await client.flowui_verify_media_visible(ids))
    if not res.get("ok"):
        raise FlowUiDriverError(
            ERR_REFERENCES_NOT_VISIBLE,
            f"missing={res.get('missing')} visible={res.get('visible_count')}"
            f"/{res.get('expected_count')} (error={res.get('error')})")
    return res


# ── timeline Extend for ONE block (Boundary D) ───────────────────────────────
async def extend_block_via_ui(client, *, job_id: str, parent_title_substr: str,
                              block_index: int, position: int, prompt: str,
                              model_label: str = "Veo 3.1 - Lite",
                              confirm_live_credit_burn: bool = False,
                              dry_run: bool = True) -> dict:
    """Drive ONE Extend block through the current Flow UI.

    dry_run=True walks the full state machine up to EXTEND_READY_TO_SUBMIT
    (prompt inserted + read back) and STOPS — zero credit. Live requires the
    kill switch AND explicit confirmation AND the per-block route lock.
    """
    if not prompt or _BLOCK_HEADER_MARKER in prompt and prompt.count(_BLOCK_HEADER_MARKER) > 1:
        raise FlowUiDriverError(ERR_MULTI_BLOCK_PROMPT,
                                "extend prompt must be exactly ONE block")
    states: list = []

    def mark(state: str, **kw):
        states.append({"state": state, **kw})

    # ── route-exclusivity lock: SAME stage key family as direct-RPC Extend ──
    # (video_production_orchestrator._stage_key uses sha256(job|EXTEND|payload))
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
    idem = _orch._stage_key(
        job, "EXTEND", f"{parent_op}|{_nx._prompt_hash(prompt)}|pos{position}")
    existing = await crud.get_video_job_side_effect(idem)
    if existing and existing.get("submission_state") != "NOT_ATTEMPTED":
        raise FlowUiDriverError(
            ERR_ROUTE_LOCKED,
            f"block pos{position} already submitted via "
            f"{existing.get('stage')} (state={existing.get('submission_state')}) — "
            "UI and direct-RPC can never double-submit the same block")

    # ── open the EXACT current video ─────────────────────────────────────────
    mark(S_CURRENT_VIDEO_OPENING, parent=parent_op)
    opened = _res(await client.flowui_open_video(parent_title_substr))
    if not opened.get("ok"):
        raise FlowUiDriverError("CURRENT_VIDEO_OPEN_FAILED",
                                str(opened.get("error")))
    mark(S_CURRENT_VIDEO_CONFIRMED, view=(opened.get("state") or {}).get("view"))

    # ── Add Clip → Extend (model) ────────────────────────────────────────────
    mark(S_EXTEND_CONTROL_OPENING)
    menu = _res(await client.flowui_add_clip_extend(model_label))
    if not menu.get("ok"):
        raise FlowUiDriverError("EXTEND_CONTROL_FAILED", str(menu.get("error")))
    mark(S_EXTEND_PROMPT_READY, menu_item=menu.get("menu_item"))

    # ── Block-N prompt ONLY, verified by read-back ───────────────────────────
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

    # ── LIVE submit: kill switch + explicit confirm + reserve the block ─────
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
        raise FlowUiDriverError("EXTEND_SUBMIT_FAILED", str(submitted.get("error")))
    mark(S_EXTEND_SUBMITTED)
    return {"ok": True, "dry_run": False, "states": states,
            "idempotency_key": idem, "parent_operation_id": parent_op}


# ── Download Project (Boundary E) ────────────────────────────────────────────
async def download_project_via_ui(client, *, job_id: Optional[str],
                                  project_id: Optional[str],
                                  register: bool = True) -> dict:
    """Three-dot menu → Download Project → capture the ACTUAL browser download,
    hash + inspect it, and register it HONESTLY (ZIP = project archive).
    Zero credit (captured contract: client-side ZIP blob)."""
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
        "artifact_kind": artifact_kind,       # HONEST: never "video" for a ZIP
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
        # EXISTING durable-job metadata mechanism (stage_state_json on
        # video_production_job) — no migration, no schema CHECK conflicts
        # (generated_artifact/generation_result constrain kind to video|image,
        # and a ZIP must NEVER be registered as either). Content-addressed key:
        # identical bytes can never double-register.
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
                }
                await crud.update_video_production_job_full(
                    job_id, stage_state_json=json.dumps(state))
            registered = True
        result["artifact_id"] = artifact_id
        result["registered"] = registered
        if not registered:
            # ad-hoc download without a durable job: full metadata returned to
            # the caller; honesty preserved (never silently claimed persisted).
            result["registered_reason"] = "NO_DURABLE_JOB_ROW_FOR_JOB_ID"
        result["state"] = (S_ARTIFACT_REGISTERED if registered
                           else S_DOWNLOAD_COMPLETED)
    return result
