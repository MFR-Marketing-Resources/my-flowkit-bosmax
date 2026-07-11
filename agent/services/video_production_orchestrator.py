"""Durable, resumable, server-owned FULL-VIDEO job orchestration.

ONE logical job owns the whole lifecycle and is created BEFORE any credit-consuming
operation (create-before-initial):

  CREATED → AUTHORIZED → INITIAL_SUBMITTING → INITIAL_POLLING → INITIAL_READY
          → EXTEND_CONTEXT_READY → EXTEND_SUBMITTING → EXTEND_POLLING → EXTEND_READY
          → CONCAT_SUBMITTING → CONCAT_POLLING → FINAL_SAVING → COMPLETE

Durability contract (survives browser refresh, tab close, backend/worker restart,
extension reconnect, delayed responses, concurrent tabs):
  * every transition is persisted;
  * every credit-consuming side effect (INITIAL, EXTEND, CONCAT) is reserved
    ATOMICALLY at the DB (unique idempotency key) BEFORE submit — a race can only
    have one winner; everyone else RESUMES from the persisted structured state;
  * a re-entry NEVER re-submits: it reads submission_state and resumes/returns;
  * `advance_job` is the single resumable entry — safe to call repeatedly.

Authorization: one whole-job plan is fingerprinted (product / asset hash / prompts /
duration / engine-model / segment plan / operation counts / execution package). A
single expiring, job-bound, fingerprint-bound token authorizes the entire plan.
Per-stage submits are gated by that one authorization; a changed plan is rejected.

Credit truth is STRUCTURED (submission_state / credit_state / retry_safety /
effective_submit_count) — never inferred from error strings.

The proven generators are reused, not rewritten: INITIAL calls the injected
initial-generation adapter (existing one-door lane), EXTEND calls the native-extend
runtime, CONCAT calls the final-timeline runtime.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from agent.db import crud as _crud
from agent.services import google_flow_final_timeline_runtime as _ft
from agent.services import google_flow_native_extend_runtime as _nx

# ── states ───────────────────────────────────────────────────────────────────
S_CREATED = "CREATED"
S_AUTHORIZED = "AUTHORIZED"
S_INITIAL_SUBMITTING = "INITIAL_SUBMITTING"
S_INITIAL_POLLING = "INITIAL_POLLING"
S_INITIAL_READY = "INITIAL_READY"
S_EXTEND_CONTEXT_READY = "EXTEND_CONTEXT_READY"
S_EXTEND_SUBMITTING = "EXTEND_SUBMITTING"
S_EXTEND_POLLING = "EXTEND_POLLING"
S_EXTEND_READY = "EXTEND_READY"
S_CONCAT_SUBMITTING = "CONCAT_SUBMITTING"
S_CONCAT_POLLING = "CONCAT_POLLING"
S_FINAL_SAVING = "FINAL_SAVING"
S_COMPLETE = "COMPLETE"

F_INITIAL = "INITIAL_FAILED"
F_EXTEND = "EXTEND_FAILED"
F_FINAL = "FINAL_RENDER_FAILED"
F_AUTH = "AUTHORIZATION_INVALID"

# structured side-effect vocab
SUB_NOT_ATTEMPTED, SUB_SUBMITTED, SUB_UNCERTAIN, SUB_TERMINAL = (
    "NOT_ATTEMPTED", "SUBMITTED", "UNCERTAIN", "TERMINAL")
CR_NOT_SPENT, CR_MAY_HAVE_SPENT, CR_SPENT, CR_UNKNOWN = (
    "NOT_SPENT", "MAY_HAVE_SPENT", "SPENT", "UNKNOWN")
RS_SAFE, RS_RESUME_ONLY, RS_BLOCKED = "SAFE", "RESUME_ONLY", "BLOCKED"

AUTHORIZATION_TTL_SECONDS = 600
_SEGMENT_SECONDS = 8


class OrchestratorError(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}:{detail}" if detail else code)


def orchestrator_enabled() -> bool:
    return os.environ.get("NATIVE_EXTEND_ENABLED", "0").strip().lower() in (
        "1", "true", "yes", "on")


# ── identity + plan fingerprints (Mission 2 / 6) ─────────────────────────────
def _canonical(intent: dict[str, Any]) -> str:
    return json.dumps(intent, sort_keys=True, separators=(",", ":"), default=str)


def compute_plan_fingerprint(intent: dict[str, Any]) -> str:
    """Fingerprint the WHOLE reviewed job: any change to product / asset hash /
    prompt fingerprints / duration / engine-model / segment plan / operation counts
    / execution package invalidates the authorization."""
    keys = (
        "product_id", "approved_asset_sha256", "requested_duration_seconds",
        "engine", "model", "aspect_ratio", "execution_package_id",
        "initial_prompt_fingerprint", "continuation_prompt_fingerprints",
        "segment_plan", "operation_counts", "execution_mode",
    )
    material = {k: intent.get(k) for k in keys}
    return hashlib.sha256(_canonical(material).encode()).hexdigest()


def compute_logical_job_key(intent: dict[str, Any]) -> str:
    """Durable logical identity created BEFORE project/source ids exist. Includes an
    explicit request nonce so two legitimate production intents with the same
    product/asset/duration remain distinct jobs."""
    keys = (
        "execution_package_id", "product_id", "approved_asset_sha256",
        "requested_duration_seconds", "initial_prompt_fingerprint",
        "execution_mode", "client_request_nonce",
    )
    material = {k: intent.get(k) for k in keys}
    return "ljk_" + hashlib.sha256(_canonical(material).encode()).hexdigest()[:24]


def build_whole_plan(requested_seconds: int) -> dict[str, Any]:
    """One reviewed plan covering initial + extend + concat operations. Credit is
    stated honestly: generation ops are credit-consuming; the concat/final render
    credit behaviour is NOT proven, so it is reported as 'unknown', never claimed."""
    segments = max(2, int(requested_seconds) // _SEGMENT_SECONDS)
    extend_ops = segments - 1
    return {
        "requested_seconds": int(requested_seconds),
        "segment_count": segments,
        "operation_counts": {
            "initial_generation": 1,
            "extend": extend_ops,
            "final_render": 1,
            "total": 1 + extend_ops + 1,
        },
        "credit_estimate": {
            "initial_generation": "credit_consuming",
            "extend": "credit_consuming",
            "final_render": "unknown",  # concat credit behaviour not proven
            "total": "unknown",
        },
    }


# ── plan + authorize (Mission 1 / 6) ─────────────────────────────────────────
async def plan_job(intent: dict[str, Any]) -> dict[str, Any]:
    """Create (or reuse) the lifecycle-owning job BEFORE any credit operation."""
    logical_key = compute_logical_job_key(intent)
    existing = await _crud.get_video_production_job_by_logical_key(logical_key)
    plan = build_whole_plan(int(intent.get("requested_duration_seconds") or 16))
    intent_for_fp = {**intent, "segment_plan": plan["segment_count"],
                     "operation_counts": plan["operation_counts"]}
    fingerprint = compute_plan_fingerprint(intent_for_fp)

    if existing:
        return {"job_id": existing["job_id"], "status": existing["status"],
                "logical_job_key": logical_key, "plan": plan,
                "plan_fingerprint": existing.get("plan_fingerprint") or fingerprint,
                "reused": True}

    job_id = "vj_" + secrets.token_hex(6)
    await _crud.create_video_production_job_full(
        job_id, logical_job_key=logical_key, status=S_CREATED,
        requested_duration_seconds=plan["requested_seconds"],
        product_id=intent.get("product_id"), product_name=intent.get("product_name"),
        execution_package_id=intent.get("execution_package_id"),
        approved_asset_id=intent.get("approved_asset_id"),
        approved_asset_sha256=intent.get("approved_asset_sha256"),
        engine=intent.get("engine"), model=intent.get("model"),
        aspect_ratio=intent.get("aspect_ratio"),
        plan_fingerprint=fingerprint,
        whole_plan_json=json.dumps(plan),
        segment_media_ids_json=json.dumps([]))
    # Re-read: a racing create for the same logical key made INSERT OR IGNORE a
    # no-op, so the persisted job may be the other caller's — always authoritative.
    row = await _crud.get_video_production_job_by_logical_key(logical_key)
    return {"job_id": row["job_id"], "status": row["status"],
            "logical_job_key": logical_key, "plan": plan,
            "plan_fingerprint": row.get("plan_fingerprint") or fingerprint,
            "reused": row["job_id"] != job_id}


async def authorize_job(job_id: str, *, confirmed_plan_fingerprint: str,
                        now: Optional[float] = None) -> dict[str, Any]:
    """Issue ONE expiring, single-use, job-bound, fingerprint-bound authorization."""
    job = await _crud.get_video_production_job(job_id)
    if not job:
        raise OrchestratorError("VIDEO_JOB_NOT_FOUND", job_id)
    if job.get("plan_fingerprint") != confirmed_plan_fingerprint:
        raise OrchestratorError(
            "PLAN_FINGERPRINT_MISMATCH",
            "the reviewed plan changed (product/asset/prompt/duration/count) — re-plan")
    now = time.time() if now is None else now
    token = "auth_" + secrets.token_urlsafe(24)
    expires_at = now + AUTHORIZATION_TTL_SECONDS
    await _crud.update_video_production_job_full(
        job_id, status=S_AUTHORIZED, authorization_token=token,
        authorization_expires_at=str(expires_at), error_code=None)
    return {"job_id": job_id, "authorization_token": token,
            "expires_in_seconds": AUTHORIZATION_TTL_SECONDS,
            "plan_fingerprint": confirmed_plan_fingerprint}


def _check_authorization(job: dict, token: str, now: float) -> None:
    if not orchestrator_enabled():
        raise OrchestratorError(_ft.FINAL_TIMELINE_DISABLED, "NATIVE_EXTEND_ENABLED!=1")
    if not token or token != job.get("authorization_token"):
        raise OrchestratorError(F_AUTH, "authorization token mismatch")
    exp = job.get("authorization_expires_at")
    if exp and now > float(exp):
        raise OrchestratorError(F_AUTH, "authorization expired — re-authorize")


# ── structured side-effect helpers (Mission 7) ──────────────────────────────
def _stage_key(job: dict, stage: str, payload: str) -> str:
    base = f"{job['job_id']}|{stage}|{payload}"
    return f"se_{stage.lower()}_" + hashlib.sha256(base.encode()).hexdigest()[:24]


async def _reserve_or_resume(idem: str, job_id: str, stage: str) -> dict:
    res = await _crud.reserve_video_job_side_effect(idem, job_id=job_id, stage=stage)
    return res


# ── the resumable engine (Mission 3 / 4 / 8) ─────────────────────────────────
InitialGenFn = Callable[[dict], Awaitable[dict]]


async def advance_job(
    client, job_id: str, *,
    authorization_token: str,
    generate_initial: InitialGenFn,
    continuation_prompt: str = "continue the same shot, same product, same scale",
    now: Optional[float] = None,
    poll_interval_s: int = 5,
    out_dir: Optional[Path] = None,
    resume_only: bool = False,
) -> dict:
    """Drive the job forward from its persisted state; resume-safe, never double-submit.

    Returns the job's current structured status. Idempotent: calling again resumes.
    Raises OrchestratorError only on authorization / hard failures (persisted too).
    """
    now = time.time() if now is None else now
    job = await _crud.get_video_production_job(job_id)
    if not job:
        raise OrchestratorError("VIDEO_JOB_NOT_FOUND", job_id)
    if job.get("status") == S_COMPLETE:
        return await get_job_status(job_id)
    _check_authorization(job, authorization_token, now)

    # ── INITIAL segment (reuse existing generator via injected adapter) ──────
    if not job.get("initial_operation_id"):
        idem = _stage_key(job, "INITIAL", job["logical_job_key"])
        if resume_only:
            _existing = await _crud.get_video_job_side_effect(idem)
            if not _existing or _existing.get("submission_state") == SUB_NOT_ATTEMPTED:
                return await get_job_status(job_id)  # nothing in flight; await human start
        r = await _reserve_or_resume(idem, job_id, "INITIAL")
        if r["reserved"]:
            await _crud.update_video_production_job_full(job_id, status=S_INITIAL_SUBMITTING)
            await _crud.increment_side_effect_submit_count(idem)
            await _crud.update_video_job_side_effect(
                idem, submission_state=SUB_SUBMITTED, credit_state=CR_MAY_HAVE_SPENT,
                retry_safety=RS_RESUME_ONLY)
            try:
                seg = await generate_initial(job)
            except Exception as exc:  # noqa: BLE001
                await _crud.update_video_job_side_effect(
                    idem, submission_state=SUB_UNCERTAIN, credit_state=CR_MAY_HAVE_SPENT,
                    retry_safety=RS_BLOCKED, detail=str(exc)[:200])
                await _crud.update_video_production_job_full(
                    job_id, status=F_INITIAL, error_code=F_INITIAL)
                raise OrchestratorError(F_INITIAL, str(exc)[:200]) from exc
            await _crud.update_video_production_job_full(
                job_id, status=S_INITIAL_READY,
                initial_operation_id=seg["operation_id"],
                initial_media_id=seg.get("media_id") or seg["operation_id"],
                initial_workflow_id=seg.get("workflow_id"),
                project_id=seg.get("project_id"), scene_id=seg.get("scene_id"),
                segment_media_ids_json=json.dumps([seg["operation_id"]]))
            if seg.get("media_id") and seg.get("scene_id"):
                try:
                    await _crud.set_artifact_scene(seg["media_id"], seg["scene_id"])
                except Exception:  # noqa: BLE001 — evidence best-effort
                    pass
            await _crud.update_video_job_side_effect(
                idem, submission_state=SUB_TERMINAL, credit_state=CR_SPENT,
                retry_safety=RS_RESUME_ONLY, operation_ref=seg["operation_id"])
            job = await _crud.get_video_production_job(job_id)
        else:
            # already attempted by someone else — resume by structured state
            row = r["row"] or {}
            if row.get("submission_state") in (SUB_UNCERTAIN,):
                raise OrchestratorError(
                    F_INITIAL, "prior initial submit is UNCERTAIN — manual review")
            return await get_job_status(job_id)  # in-flight elsewhere; poll

    # ── EXTEND continuation(s) via the native-extend runtime (own idem too) ──
    if not job.get("extend_child_operation_id"):
        source_op = job["initial_operation_id"]
        idem = _stage_key(job, "EXTEND", f"{source_op}|{_nx._prompt_hash(continuation_prompt)}")
        if resume_only:
            _existing = await _crud.get_video_job_side_effect(idem)
            if not _existing or _existing.get("submission_state") == SUB_NOT_ATTEMPTED:
                return await get_job_status(job_id)  # nothing in flight; await human start
        r = await _reserve_or_resume(idem, job_id, "EXTEND")
        if r["reserved"]:
            await _crud.update_video_production_job_full(job_id, status=S_EXTEND_SUBMITTING)
            await _crud.increment_side_effect_submit_count(idem)
            await _crud.update_video_job_side_effect(
                idem, submission_state=SUB_SUBMITTED, credit_state=CR_MAY_HAVE_SPENT,
                retry_safety=RS_RESUME_ONLY)
            blocks = [_nx.ExtendBlock(block_index=2, position=1,
                                      prompt=continuation_prompt, is_final=True)]
            req = _nx.ExtendChainRequest(
                project_id=job["project_id"], scene_id=job["scene_id"],
                source_operation_id=source_op, blocks=blocks)
            try:
                # Kill-switch path (native_extend_enabled) authorizes this live
                # run; the whole-job authorization was already checked above.
                result = await _nx.run_native_extend_chain(
                    client, req, dry_run=False, confirm_live_credit_burn=True,
                    confirmed_extend_operation_count=1)
            except Exception as exc:  # noqa: BLE001
                uncertain = "SUBMIT" in str(exc).upper() or "TIMEOUT" in str(exc).upper()
                await _crud.update_video_job_side_effect(
                    idem, submission_state=(SUB_UNCERTAIN if uncertain else SUB_NOT_ATTEMPTED),
                    credit_state=(CR_MAY_HAVE_SPENT if uncertain else CR_NOT_SPENT),
                    retry_safety=(RS_BLOCKED if uncertain else RS_SAFE), detail=str(exc)[:200])
                await _crud.update_video_production_job_full(
                    job_id, status=F_EXTEND, error_code=F_EXTEND)
                raise OrchestratorError(F_EXTEND, str(exc)[:200]) from exc
            child = (result.get("blocks") or [{}])[-1]
            child_op = child.get("child_operation_id") or child.get("child_primary_media_id")
            if not child_op:
                await _crud.update_video_job_side_effect(
                    idem, submission_state=SUB_UNCERTAIN, credit_state=CR_MAY_HAVE_SPENT,
                    retry_safety=RS_BLOCKED, detail="no child op in extend result")
                raise OrchestratorError(F_EXTEND, "extend produced no child operation")
            segs = json.loads(job.get("segment_media_ids_json") or "[]") + [child_op]
            await _crud.update_video_production_job_full(
                job_id, status=S_EXTEND_READY,
                extend_child_operation_id=child_op,
                extend_child_workflow_id=child.get("child_workflow_id"),
                segment_media_ids_json=json.dumps(segs))
            await _crud.update_video_job_side_effect(
                idem, submission_state=SUB_TERMINAL, credit_state=CR_SPENT,
                retry_safety=RS_RESUME_ONLY, operation_ref=child_op)
            job = await _crud.get_video_production_job(job_id)
        else:
            row = r["row"] or {}
            if row.get("operation_ref"):
                segs = json.loads(job.get("segment_media_ids_json") or "[]")
                if row["operation_ref"] not in segs:
                    segs.append(row["operation_ref"])
                await _crud.update_video_production_job_full(
                    job_id, status=S_EXTEND_READY,
                    extend_child_operation_id=row["operation_ref"],
                    segment_media_ids_json=json.dumps(segs))
                job = await _crud.get_video_production_job(job_id)
            elif row.get("submission_state") == SUB_UNCERTAIN:
                raise OrchestratorError(F_EXTEND, "prior extend submit UNCERTAIN")
            else:
                return await get_job_status(job_id)

    # ── CONCAT / final render — DB-atomic idempotency is critical here ───────
    if not job.get("final_media_id"):
        segments = json.loads(job.get("segment_media_ids_json") or "[]")
        idem = _stage_key(job, "CONCAT", "+".join(sorted(segments)))
        if resume_only:
            _existing = await _crud.get_video_job_side_effect(idem)
            if not _existing or _existing.get("submission_state") == SUB_NOT_ATTEMPTED:
                return await get_job_status(job_id)
        r = await _reserve_or_resume(idem, job_id, "CONCAT")
        if not r["reserved"]:
            row = r["row"] or {}
            if row.get("submission_state") == SUB_TERMINAL and job.get("final_media_id"):
                return await get_job_status(job_id)
            # a concat is SUBMITTED/UNCERTAIN elsewhere — resume via finalize's own
            # persisted job-name (never a second concat submit).
        await _crud.increment_side_effect_submit_count(idem)
        await _crud.update_video_job_side_effect(
            idem, submission_state=SUB_SUBMITTED, credit_state=CR_UNKNOWN,
            retry_safety=RS_RESUME_ONLY)
        try:
            done = await _ft.finalize_timeline(
                client, job_id=job_id, segment_media_ids=segments,
                requested_seconds=int(job.get("requested_duration_seconds") or 16),
                out_dir=out_dir or (Path("output") / "retrieved"),
                dry_run=False, confirm_live_credit_burn=True,
                poll_interval_s=poll_interval_s)
        except _ft.FinalTimelineError as exc:
            uncertain = exc.code in (_ft.FAIL_FINAL_SUBMIT_UNCERTAIN, _ft.FAIL_FINAL_RENDER)
            await _crud.update_video_job_side_effect(
                idem, submission_state=(SUB_UNCERTAIN if uncertain else SUB_NOT_ATTEMPTED),
                credit_state=CR_UNKNOWN, retry_safety=RS_BLOCKED, detail=str(exc)[:200])
            await _crud.update_video_production_job_full(
                job_id, status=F_FINAL, error_code=exc.code)
            raise OrchestratorError(F_FINAL, str(exc)[:200]) from exc
        await _crud.update_video_job_side_effect(
            idem, submission_state=SUB_TERMINAL, credit_state=CR_UNKNOWN,
            retry_safety=RS_RESUME_ONLY, operation_ref=done.get("final_concat_job_name"))
        # register the ONE deliverable in the library
        try:
            await _crud.insert_generated_artifact(
                done["final_media_id"], job_id=job_id, mode="EXTEND",
                artifact_kind="video", local_path=done["local_path"],
                size_mb=done.get("size_mb"), project_id=job.get("project_id"),
                duration_used=int(done.get("measured_duration_s") or 0))
        except Exception:  # noqa: BLE001
            pass

    return await get_job_status(job_id)


async def get_job_status(job_id: str) -> dict:
    """Structured, refresh-safe status the UI restores on mount (no raw ids leaked
    to normal mode by the caller; this is the full record — the API projects it)."""
    job = await _crud.get_video_production_job(job_id)
    if not job:
        raise OrchestratorError("VIDEO_JOB_NOT_FOUND", job_id)
    plan = json.loads(job.get("whole_plan_json") or "{}")
    # Structured credit truth aggregated from the side-effect ledger (never strings).
    effects = await _crud.list_video_job_side_effects(job_id)
    states = {e.get("credit_state") for e in effects}
    if not effects or states <= {CR_NOT_SPENT}:
        credit_summary = CR_NOT_SPENT
    elif CR_SPENT in states or CR_MAY_HAVE_SPENT in states:
        credit_summary = CR_MAY_HAVE_SPENT if CR_MAY_HAVE_SPENT in states else CR_SPENT
    else:
        credit_summary = CR_UNKNOWN
    human = _human_stage(job.get("status"))
    return {
        "job_id": job_id,
        "logical_job_key": job.get("logical_job_key"),
        "status": job.get("status"),
        "human_stage": human,
        "error_code": job.get("error_code"),
        "requested_duration_seconds": job.get("requested_duration_seconds"),
        "product_name": job.get("product_name"),
        "plan": plan,
        "final_media_id": job.get("final_media_id"),
        "final_duration_s": job.get("final_duration_s"),
        "complete": job.get("status") == S_COMPLETE,
        "credit_summary": credit_summary,
        "no_credit_used": credit_summary == CR_NOT_SPENT,
    }


_HUMAN = {
    S_CREATED: "Preparing video", S_AUTHORIZED: "Preparing video",
    S_INITIAL_SUBMITTING: "Generating video", S_INITIAL_POLLING: "Generating video",
    S_INITIAL_READY: "Generating video",
    S_EXTEND_CONTEXT_READY: "Extending video", S_EXTEND_SUBMITTING: "Extending video",
    S_EXTEND_POLLING: "Extending video", S_EXTEND_READY: "Extending video",
    S_CONCAT_SUBMITTING: "Preparing final video", S_CONCAT_POLLING: "Preparing final video",
    S_FINAL_SAVING: "Preparing final video", S_COMPLETE: "Video ready",
    F_INITIAL: "The first part could not be completed.",
    F_EXTEND: "The continuation could not be completed safely.",
    F_FINAL: "The final video could not be prepared.",
    F_AUTH: "Please review and confirm the video again.",
}


def _human_stage(status: Optional[str]) -> str:
    return _HUMAN.get(status or "", "Preparing video")


async def resume_in_flight_jobs(client, *, generate_initial: InitialGenFn,
                                out_dir: Optional[Path] = None) -> list[dict]:
    """On process restart, RESUME (poll only) every in-flight authorized job — never
    a fresh credit submit. New stages wait for a human-triggered start."""
    resumed = []
    for job in await _crud.list_non_terminal_authorized_jobs():
        try:
            status = await advance_job(
                client, job["job_id"],
                authorization_token=job.get("authorization_token") or "",
                generate_initial=generate_initial, out_dir=out_dir, resume_only=True)
            resumed.append(status)
        except Exception:  # noqa: BLE001 — one bad job never blocks the sweep
            continue
    return resumed
