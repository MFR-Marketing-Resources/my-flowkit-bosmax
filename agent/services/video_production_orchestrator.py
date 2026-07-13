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

S_AUTH_EXPIRED = "AUTHORIZATION_EXPIRED"  # a not-yet-submitted stage needs re-auth
S_INITIAL_RECOVERY = "INITIAL_RECOVERY_REQUIRED"  # in-flight lane lost after restart

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

# The execution package (server-side SSOT) stores the operator's aspect in UI
# ratio form ("9:16"); the Native Extend runtime resolves its model by the
# captured enum form (EXTEND_VIDEO_MODELS keys). Map at THIS boundary only —
# an already-enum value passes through unchanged, and an unknown value still
# fails closed in the runtime (EXTEND_UNSUPPORTED_MODEL, zero credit). Live
# regression: job vj_2502426e7791 EXTEND_FAILED with detail
# "EXTEND_UNSUPPORTED_MODEL:9:16" after a successful initial.
_ASPECT_RATIO_TO_ENUM = {
    "9:16": "VIDEO_ASPECT_RATIO_PORTRAIT",
    "16:9": "VIDEO_ASPECT_RATIO_LANDSCAPE",
    "1:1": "VIDEO_ASPECT_RATIO_SQUARE",
}


def extend_aspect_ratio(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "VIDEO_ASPECT_RATIO_PORTRAIT"
    return _ASPECT_RATIO_TO_ENUM.get(raw, raw)


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


# ── plan + authorize (Mission 1 / 2 / 3 / 6) ─────────────────────────────────
async def plan_job(intent: dict[str, Any], *,
                   trust_client_authority: bool = False) -> dict[str, Any]:
    """Create (or reuse) the lifecycle-owning job BEFORE any credit operation.

    Resolves the COMPLETE production authority (product / asset / prompts) and
    fails closed with INCOMPLETE_PRODUCTION_PLAN if any required field or the exact
    reviewed prompts cannot be resolved — no authorization is ever minted for an
    incomplete plan. The resolved initial + continuation prompts are persisted and
    fingerprinted here, before authorization, so a later prompt change is a
    PLAN_FINGERPRINT_MISMATCH and each Extend runs the exact reviewed segment prompt.

    Production (trust_client_authority=False) enforces server-side SSOT: the client
    cannot override product/asset/prompt authority. A non-8s-multiple duration is
    rejected up front. A supplied fingerprint that contradicts its text is rejected.
    """
    from agent.services import production_plan_resolver as _resolver

    # Duration guard (no floor division): a Native-Extend timeline is an exact sum
    # of 8s blocks; anything else would later fail the final-duration check after
    # credits are already spent, so reject it at plan time.
    duration = int(intent.get("requested_duration_seconds") or 16)
    if not _resolver.duration_is_valid(duration):
        raise OrchestratorError(
            "INVALID_DURATION_PLAN",
            f"requested {duration}s is not a valid Native-Extend plan "
            "(must be a multiple of 8s and at least 16s, e.g. 16=[8,8], 24=[8,8,8])")

    logical_key = compute_logical_job_key(intent)
    existing = await _crud.get_video_production_job_by_logical_key(logical_key)

    try:
        authority = await _resolver.resolve_production_authority(
            intent, trust_client_authority=trust_client_authority)
    except _resolver.AuthorityMismatchError as exc:
        raise OrchestratorError(_resolver.FINGERPRINT_MISMATCH, exc.detail) from exc
    missing = authority.get("missing") or []
    if missing and not existing:
        raise OrchestratorError(
            "INCOMPLETE_PRODUCTION_PLAN",
            "missing production authority: " + ", ".join(sorted(set(missing))))

    plan = build_whole_plan(int(authority["requested_duration_seconds"]))
    conts = authority.get("continuation_prompts") or []
    intent_for_fp = {
        **intent,
        "product_id": authority.get("product_id"),
        "approved_asset_sha256": authority.get("approved_asset_sha256"),
        "requested_duration_seconds": authority["requested_duration_seconds"],
        "engine": authority.get("engine"), "model": authority.get("model"),
        "aspect_ratio": authority.get("aspect_ratio"),
        "execution_package_id": authority.get("execution_package_id"),
        "initial_prompt_fingerprint": authority.get("initial_prompt_fingerprint"),
        "continuation_prompt_fingerprints": authority.get(
            "continuation_prompt_fingerprints"),
        "segment_plan": plan["segment_count"],
        "operation_counts": plan["operation_counts"],
    }
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
        product_id=authority.get("product_id"), product_name=intent.get("product_name"),
        execution_package_id=authority.get("execution_package_id"),
        approved_asset_id=authority.get("approved_asset_id"),
        approved_asset_sha256=authority.get("approved_asset_sha256"),
        engine=authority.get("engine"), model=authority.get("model"),
        aspect_ratio=authority.get("aspect_ratio"),
        initial_mode=authority.get("initial_mode"),
        initial_prompt_text=authority.get("initial_prompt_text"),
        initial_prompt_fingerprint=authority.get("initial_prompt_fingerprint"),
        initial_asset_media_id=authority.get("initial_asset_media_id"),
        initial_reference_media_ids_json=json.dumps(
            authority.get("initial_reference_media_ids") or []),
        initial_source_mode=authority.get("initial_source_mode"),
        continuation_prompts_json=json.dumps(conts),
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
    authorization_id = "authid_" + secrets.token_hex(8)
    expires_at = now + AUTHORIZATION_TTL_SECONDS
    # Re-authorizing rotates the token AND clears any prior single-use consumption
    # so the freshly reviewed plan can start exactly once.
    await _crud.update_video_production_job_full(
        job_id, status=S_AUTHORIZED, authorization_token=token,
        authorization_id=authorization_id, authorization_issued_at=str(now),
        authorization_expires_at=str(expires_at),
        authorization_consumed_at=None, authorization_consumed_by_job_id=None,
        authorization_consumed_plan_fingerprint=None, error_code=None)
    return {"job_id": job_id, "authorization_token": token,
            "authorization_id": authorization_id,
            "expires_in_seconds": AUTHORIZATION_TTL_SECONDS,
            "plan_fingerprint": confirmed_plan_fingerprint}


# ── per-stage authorization gate (Mission 5) ─────────────────────────────────
# Authorization is required only to INITIATE a not-yet-submitted credit stage.
# Already-submitted stages resume/poll WITHOUT a live token (token expiry never
# strands an in-flight job); resume_only paths never call this at all.
_AUTH_OK = "OK"
_AUTH_EXPIRED = "EXPIRED"


def _gate_stage_start(job: dict, token: str, now: float) -> str:
    """Return _AUTH_OK to proceed with a fresh submit, or _AUTH_EXPIRED to stop
    safely and require re-authorization. Raises only on a hard invalid token or a
    disabled kill-switch (never on mere expiry)."""
    if not orchestrator_enabled():
        raise OrchestratorError(_ft.FINAL_TIMELINE_DISABLED, "NATIVE_EXTEND_ENABLED!=1")
    if not token or token != job.get("authorization_token"):
        raise OrchestratorError(F_AUTH, "authorization token mismatch")
    exp = job.get("authorization_expires_at")
    if exp and now > float(exp):
        return _AUTH_EXPIRED
    return _AUTH_OK


# ── structured side-effect helpers (Mission 7) ──────────────────────────────
def _stage_key(job: dict, stage: str, payload: str) -> str:
    base = f"{job['job_id']}|{stage}|{payload}"
    return f"se_{stage.lower()}_" + hashlib.sha256(base.encode()).hexdigest()[:24]


async def _reserve_or_resume(idem: str, job_id: str, stage: str) -> dict:
    res = await _crud.reserve_video_job_side_effect(idem, job_id=job_id, stage=stage)
    return res


# ── the resumable engine (Mission 1 / 3 / 4 / 5 / 6 / 8) ─────────────────────
InitialGenFn = Callable[[dict], Awaitable[dict]]
# Poll-only resume of a persisted in-flight initial lane. Returns a structured state
# ({"state": "DONE"/"INFLIGHT"/"RECOVERY"/"FAILED", ...}); NEVER submits.
InitialResumeFn = Callable[[dict], Awaitable[dict]]


async def _persist_initial_result(job_id: str, idem: str, seg: dict, *,
                                  bal_before, client) -> None:
    """Persist a completed INITIAL result (fresh OR resumed) with credit truth.
    Fails closed on any missing durable identity."""
    for key in ("operation_id", "project_id", "scene_id"):
        if not seg.get(key):
            await _crud.update_video_job_side_effect(
                idem, submission_state=SUB_UNCERTAIN, credit_state=CR_MAY_HAVE_SPENT,
                retry_safety=RS_BLOCKED, detail=f"initial missing {key}")
            await _crud.update_video_production_job_full(
                job_id, status=F_INITIAL, error_code=F_INITIAL)
            raise OrchestratorError(F_INITIAL, f"initial result missing {key}")
    bal_after = seg.get("credit_balance_after")
    if bal_after is None:
        bal_after = await _safe_credits(client)
    await _crud.update_video_production_job_full(
        job_id, status=S_INITIAL_READY,
        initial_operation_id=seg["operation_id"],
        initial_media_id=seg.get("media_id") or seg["operation_id"],
        initial_workflow_id=seg.get("workflow_id"),
        project_id=seg.get("project_id"), scene_id=seg.get("scene_id"),
        initial_correlation_json=json.dumps(seg.get("correlation") or None),
        segment_media_ids_json=json.dumps([seg["operation_id"]]))
    if seg.get("media_id") and seg.get("scene_id"):
        try:
            await _crud.set_artifact_scene(seg["media_id"], seg["scene_id"])
        except Exception:  # noqa: BLE001 — evidence best-effort
            pass
    await _crud.update_video_job_side_effect(
        idem, submission_state=SUB_TERMINAL,
        credit_state=_credit_state_from_balances(bal_before, bal_after),
        retry_safety=RS_RESUME_ONLY, operation_ref=seg["operation_id"],
        credit_balance_after=bal_after)


def _credit_state_from_balances(before, after) -> str:
    """SPENT only with authoritative debit evidence (a real balance decrease);
    MAY_HAVE_SPENT when a submit was accepted but no debit is proven; UNKNOWN when
    a balance is unreadable. Never inferred from success alone."""
    try:
        if before is not None and after is not None:
            return CR_SPENT if float(after) < float(before) else CR_MAY_HAVE_SPENT
    except (TypeError, ValueError):
        pass
    return CR_MAY_HAVE_SPENT


async def _safe_credits(client) -> Optional[float]:
    """Best-effort current credit balance for debit evidence; never raises."""
    getter = getattr(client, "get_credits", None)
    if getter is None:
        return None
    try:
        resp = await getter()
    except Exception:  # noqa: BLE001
        return None
    if isinstance(resp, (int, float)):
        return float(resp)
    if isinstance(resp, dict):
        for k in ("remainingCredits", "credits", "balance", "remaining"):
            v = resp.get(k) if hasattr(resp, "get") else None
            if isinstance(v, (int, float)):
                return float(v)
    return None


async def _needs_stage_gate(idem: str) -> bool:
    """True when this stage has NOT been submitted yet (initiation → auth required).
    A stage already SUBMITTED/UNCERTAIN/TERMINAL resumes without a live token."""
    existing = await _crud.get_video_job_side_effect(idem)
    return not existing or existing.get("submission_state") == SUB_NOT_ATTEMPTED


async def _stop_auth_expired(job_id: str) -> dict:
    await _crud.update_video_production_job_full(
        job_id, status=S_AUTH_EXPIRED, error_code=S_AUTH_EXPIRED)
    return await get_job_status(job_id)


async def _drive_initial_resume(job_id: str, idem: str,
                                resume_initial: Optional[InitialResumeFn],
                                client) -> dict:
    """Resume an already-submitted INITIAL by polling its persisted lane — NEVER
    submits. Completes on DONE, waits on INFLIGHT, and on a lost lane goes to
    INITIAL_RECOVERY_REQUIRED (credit may have been spent) instead of stranding."""
    if resume_initial is None:
        return await get_job_status(job_id)  # no resumer wired; just poll
    job = await _crud.get_video_production_job(job_id)
    existing = await _crud.get_video_job_side_effect(idem) or {}
    state = await resume_initial(job)
    kind = (state or {}).get("state")
    if kind == "DONE":
        await _persist_initial_result(
            job_id, idem, state["identity"],
            bal_before=existing.get("credit_balance_before"), client=client)
    elif kind == "RECOVERY":
        await _crud.update_video_job_side_effect(
            idem, submission_state=SUB_UNCERTAIN, credit_state=CR_MAY_HAVE_SPENT,
            retry_safety=RS_BLOCKED, detail=str(state.get("detail"))[:200])
        await _crud.update_video_production_job_full(
            job_id, status=S_INITIAL_RECOVERY, error_code=S_INITIAL_RECOVERY)
    elif kind == "FAILED":
        await _crud.update_video_job_side_effect(
            idem, submission_state=SUB_UNCERTAIN, credit_state=CR_MAY_HAVE_SPENT,
            retry_safety=RS_BLOCKED, detail=str(state.get("detail"))[:200])
        await _crud.update_video_production_job_full(
            job_id, status=F_INITIAL, error_code=F_INITIAL)
    # INFLIGHT (or unknown) → leave state as-is; caller polls again
    return await get_job_status(job_id)


async def advance_job(
    client, job_id: str, *,
    authorization_token: str,
    generate_initial: InitialGenFn,
    resume_initial: Optional[InitialResumeFn] = None,
    now: Optional[float] = None,
    poll_interval_s: int = 5,
    out_dir: Optional[Path] = None,
    resume_only: bool = False,
) -> dict:
    """Drive the job forward from its persisted state; resume-safe, never double-submit.

    Authorization gates only the INITIATION of a not-yet-submitted credit stage
    (Mission 5): a stage already submitted resumes/polls without a live token, so
    token expiry never strands an in-flight job. resume_only never submits.
    Each Extend runs the exact persisted reviewed prompt for its segment (Mission 3).

    A mid-flight-submitted INITIAL is RESUMED (poll-only) via `resume_initial` against
    the persisted one-door lane handle — never re-submitted. If the lane handle is
    lost after a restart, the job goes to INITIAL_RECOVERY_REQUIRED (credit may have
    been spent) rather than getting silently stuck or double-spending.
    """
    now = time.time() if now is None else now
    job = await _crud.get_video_production_job(job_id)
    if not job:
        raise OrchestratorError("VIDEO_JOB_NOT_FOUND", job_id)
    if job.get("status") == S_COMPLETE:
        return await get_job_status(job_id)

    # ── INITIAL segment via the injected one-door adapter (Mission 1 / 5) ────
    if not job.get("initial_operation_id"):
        idem = _stage_key(job, "INITIAL", job["logical_job_key"])
        existing = await _crud.get_video_job_side_effect(idem)
        not_yet_submitted = (
            not existing or existing.get("submission_state") == SUB_NOT_ATTEMPTED)

        if not_yet_submitted:
            if resume_only:
                return await get_job_status(job_id)  # await human start
            if _gate_stage_start(job, authorization_token, now) == _AUTH_EXPIRED:
                return await _stop_auth_expired(job_id)
            r = await _reserve_or_resume(idem, job_id, "INITIAL")
            if not r["reserved"]:
                # lost the reserve race to a concurrent caller — resume, don't submit
                return await _drive_initial_resume(job_id, idem, resume_initial, client)
            bal_before = await _safe_credits(client)
            await _crud.update_video_production_job_full(job_id, status=S_INITIAL_SUBMITTING)
            await _crud.increment_side_effect_submit_count(idem)
            await _crud.update_video_job_side_effect(
                idem, submission_state=SUB_SUBMITTED, credit_state=CR_MAY_HAVE_SPENT,
                retry_safety=RS_RESUME_ONLY, credit_balance_before=bal_before)
            try:
                seg = await generate_initial(job)
            except Exception as exc:  # noqa: BLE001
                await _crud.update_video_job_side_effect(
                    idem, submission_state=SUB_UNCERTAIN, credit_state=CR_MAY_HAVE_SPENT,
                    retry_safety=RS_BLOCKED, detail=str(exc)[:200])
                await _crud.update_video_production_job_full(
                    job_id, status=F_INITIAL, error_code=F_INITIAL)
                raise OrchestratorError(F_INITIAL, str(exc)[:200]) from exc
            await _persist_initial_result(job_id, idem, seg, bal_before=bal_before, client=client)
            job = await _crud.get_video_production_job(job_id)
        else:
            # ALREADY SUBMITTED (this run or a crashed prior run) — resume poll-only.
            if existing.get("submission_state") == SUB_UNCERTAIN:
                # already reconciled to RECOVERY/failed — surface, never resubmit
                return await get_job_status(job_id)
            resumed = await _drive_initial_resume(job_id, idem, resume_initial, client)
            job = await _crud.get_video_production_job(job_id)
            if not job.get("initial_operation_id"):
                return resumed  # still in-flight / recovery — poll again later

    # ── EXTEND continuation(s): one per reviewed segment prompt (Mission 3) ──
    continuations = sorted(
        json.loads(job.get("continuation_prompts_json") or "[]"),
        key=lambda c: int(c.get("position") or 0))
    if not continuations:
        await _crud.update_video_production_job_full(
            job_id, status=F_EXTEND, error_code="CONTINUATION_PROMPT_MISSING")
        raise OrchestratorError(F_EXTEND, "no reviewed continuation prompt bound to job")

    for cont in continuations:
        segments = json.loads(job.get("segment_media_ids_json") or "[]")
        position = int(cont.get("position") or 0)
        if len(segments) > position:
            continue  # this segment's child already produced
        parent_op = segments[-1]
        prompt = cont["prompt"]
        idem = _stage_key(
            job, "EXTEND", f"{parent_op}|{_nx._prompt_hash(prompt)}|pos{position}")
        if await _needs_stage_gate(idem):
            if resume_only:
                return await get_job_status(job_id)
            if _gate_stage_start(job, authorization_token, now) == _AUTH_EXPIRED:
                return await _stop_auth_expired(job_id)
        r = await _reserve_or_resume(idem, job_id, "EXTEND")
        # retry_safety=SAFE contract: a pre-submit fail-closed error leaves the
        # row NOT_ATTEMPTED / NOT_SPENT with no operation_ref — provably zero
        # provider side effect. That is the ONE retryable state; without this,
        # the stale row holds the idempotency key forever and the job can never
        # resume (live: vj_2502426e7791 stuck AUTHORIZED after
        # EXTEND_UNSUPPORTED_MODEL). UNCERTAIN/SUBMITTED rows stay non-retryable.
        _row = r["row"] or {}
        _safe_retry = (
            not r["reserved"]
            and not _row.get("operation_ref")
            and _row.get("submission_state") == SUB_NOT_ATTEMPTED
            and _row.get("retry_safety") == RS_SAFE
        )
        if r["reserved"] or _safe_retry:
            await _crud.update_video_production_job_full(job_id, status=S_EXTEND_SUBMITTING)
            await _crud.increment_side_effect_submit_count(idem)
            await _crud.update_video_job_side_effect(
                idem, submission_state=SUB_SUBMITTED, credit_state=CR_MAY_HAVE_SPENT,
                retry_safety=RS_RESUME_ONLY)
            blocks = [_nx.ExtendBlock(block_index=position + 1, position=position,
                                      prompt=prompt, is_final=bool(cont.get("is_final")))]
            req = _nx.ExtendChainRequest(
                project_id=job["project_id"], scene_id=job["scene_id"],
                source_operation_id=parent_op, blocks=blocks,
                aspect_ratio=extend_aspect_ratio(job.get("aspect_ratio")))
            try:
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
                await _crud.update_video_production_job_full(
                    job_id, status=F_EXTEND, error_code=F_EXTEND)
                raise OrchestratorError(F_EXTEND, "extend produced no child operation")
            segs = segments + [child_op]
            await _crud.update_video_production_job_full(
                job_id, status=S_EXTEND_READY,
                extend_child_operation_id=child_op,
                extend_child_workflow_id=child.get("child_workflow_id"),
                segment_media_ids_json=json.dumps(segs))
            await _crud.update_video_job_side_effect(
                idem, submission_state=SUB_TERMINAL, credit_state=CR_MAY_HAVE_SPENT,
                retry_safety=RS_RESUME_ONLY, operation_ref=child_op)
            job = await _crud.get_video_production_job(job_id)
        else:
            row = r["row"] or {}
            if row.get("operation_ref"):
                segs = segments
                if row["operation_ref"] not in segs:
                    segs = segs + [row["operation_ref"]]
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
        if await _needs_stage_gate(idem):
            if resume_only:
                return await get_job_status(job_id)
            if _gate_stage_start(job, authorization_token, now) == _AUTH_EXPIRED:
                return await _stop_auth_expired(job_id)
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
        # PR321 closure diagnostics: canonical server-derived surface mode and the
        # exact output-correlation evidence bound at INITIAL completion.
        "initial_source_mode": job.get("initial_source_mode"),
        "initial_correlation": json.loads(job.get("initial_correlation_json") or "null"),
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
    S_AUTH_EXPIRED: "Please review and confirm the video again.",
    S_INITIAL_RECOVERY: "The first part is being reconciled after an interruption.",
    F_INITIAL: "The first part could not be completed.",
    F_EXTEND: "The continuation could not be completed safely.",
    F_FINAL: "The final video could not be prepared.",
    F_AUTH: "Please review and confirm the video again.",
}


def _human_stage(status: Optional[str]) -> str:
    return _HUMAN.get(status or "", "Preparing video")


async def resume_in_flight_jobs(client, *, generate_initial: InitialGenFn,
                                resume_initial: Optional[InitialResumeFn] = None,
                                out_dir: Optional[Path] = None) -> list[dict]:
    """On process restart, RESUME (poll only) every in-flight authorized job — never
    a fresh credit submit. A mid-flight initial is polled via its persisted lane
    handle (or reconciled to INITIAL_RECOVERY_REQUIRED). New stages wait for a
    human-triggered start."""
    resumed = []
    for job in await _crud.list_non_terminal_authorized_jobs():
        try:
            status = await advance_job(
                client, job["job_id"],
                authorization_token=job.get("authorization_token") or "",
                generate_initial=generate_initial, resume_initial=resume_initial,
                out_dir=out_dir, resume_only=True)
            resumed.append(status)
        except Exception:  # noqa: BLE001 — one bad job never blocks the sweep
            continue
    return resumed
