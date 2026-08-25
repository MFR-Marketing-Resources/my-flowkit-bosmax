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
F_FINAL_ARTIFACT = "FINAL_ARTIFACT_DELIVERY_FAILED"
F_AUTH = "AUTHORIZATION_INVALID"
OWNER_RECOVERY_HOLD_CODE = "OWNER_AUTHORIZED_RECOVERY_HOLD"
OWNER_RECOVERY_HOLD_VERSION = 1

# structured side-effect vocab
SUB_NOT_ATTEMPTED, SUB_SUBMITTED, SUB_UNCERTAIN, SUB_TERMINAL = (
    "NOT_ATTEMPTED", "SUBMITTED", "UNCERTAIN", "TERMINAL")
CR_NOT_SPENT, CR_MAY_HAVE_SPENT, CR_SPENT, CR_UNKNOWN = (
    "NOT_SPENT", "MAY_HAVE_SPENT", "SPENT", "UNKNOWN")
RS_SAFE, RS_RESUME_ONLY, RS_BLOCKED = "SAFE", "RESUME_ONLY", "BLOCKED"

# One-door lane failures that are PROVABLY pre-generation (the lane refuses
# locally or Google's anti-abuse layer rejects the request before any
# generation starts — no credit is ever debited; #216 and the whole P4 ramp
# confirmed every one of these at 0 credit). An INITIAL failure carrying one
# of these signatures is SAFE to retry even when the lane handle was already
# persisted, because the lane job existed but never submitted a generation.
ZERO_CREDIT_REJECTION_SIGNATURES = (
    "NO_OPEN_EDITOR",
    "CAPTCHA_FAILED",
    "RATE_LIMITED",
    "CONTENT_BUILD_MISMATCH",
    "Extension not connected",
    "VIDEO_JOB_IN_FLIGHT",
)

# EXTEND error codes raised AFTER the generate_video_extend RPC (provider was
# touched). Credit-honesty: an extend failure carrying one of these MUST NOT be
# classified NOT_ATTEMPTED / NOT_SPENT / SAFE — the extend may have started a
# credit-bearing child even when we could not extract it (live: vj_bb28f65c189e
# EXTEND_CHILD_MEDIA_ID_MISSING was wrongly marked SAFE by fragile substring
# matching). PRE-RPC failures (contract/validation before submit) stay SAFE.
_EXTEND_POST_RPC_CODES = frozenset({
    _nx.EXTEND_REQUEST_REJECTED,
    _nx.EXTEND_CHILD_MEDIA_ID_MISSING,
    _nx.EXTEND_LINEAGE_MISMATCH,
    _nx.EXTEND_OPERATION_TIMEOUT,
    _nx.EXTEND_OPERATION_FAILED,
})

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
        "segment_plan", "operation_counts", "execution_mode", "surface_lane",
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
        "execution_mode", "surface_lane", "client_request_nonce",
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
    from agent.services.video_surface_provenance import (
        VideoSurfaceProvenanceError,
        resolve_surface_lane,
    )
    try:
        surface_lane = resolve_surface_lane(
            explicit=intent.get("surface_lane"),
            mode=authority.get("initial_mode"),
            source_mode=authority.get("initial_source_mode"),
            execution_mode=intent.get("execution_mode"),
        )
    except VideoSurfaceProvenanceError as exc:
        raise OrchestratorError(exc.code, str(exc)) from exc
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
        "surface_lane": surface_lane,
    }
    fingerprint = compute_plan_fingerprint(intent_for_fp)

    if existing:
        return {"job_id": existing["job_id"], "status": existing["status"],
                "logical_job_key": logical_key, "plan": plan,
                "plan_fingerprint": existing.get("plan_fingerprint") or fingerprint,
                "surface_lane": existing.get("surface_lane") or surface_lane,
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
         surface_lane=surface_lane,
         transport_mode=authority.get("initial_mode"),
         source_mode=authority.get("initial_source_mode"),
         provider_generation_type=(
             "native_extend"
             if str(intent.get("execution_mode") or "").upper() == "HYBRID_EXTEND"
             else None
         ),
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
            "surface_lane": row.get("surface_lane") or surface_lane,
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
InitialPrepareFn = Callable[[dict], Awaitable[dict]]
BridgePhaseFn = Callable[[Optional[dict]], Awaitable[Any]]

BRIDGE_LINEAGE_KEY = "bridge_lineage_v1"
BRIDGE_LINEAGE_VERSION = 1
_BRIDGE_ROOT_FIELDS = (
    "installation_id",
    "extension_build",
    "flow_project_id",
)
_BRIDGE_RECEIPT_FIELDS = (
    "lease_id",
    "connection_id",
    "connection_epoch",
    "installation_id",
    "extension_session_id",
    "extension_build",
    "flow_tab_id",
    "flow_url",
    "flow_project_id",
    "released",
    "released_at",
    "receipt_state",
)


def _decode_stage_state(raw: Any) -> dict:
    if raw in (None, ""):
        return {}
    try:
        state = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError) as exc:
        raise OrchestratorError(
            "VIDEO_STAGE_STATE_INVALID", "stage_state_json is not valid JSON"
        ) from exc
    if not isinstance(state, dict):
        raise OrchestratorError(
            "VIDEO_STAGE_STATE_INVALID", "stage_state_json must be an object"
        )
    return dict(state)


async def merge_video_production_job_stage_state(
    job_id: str,
    updates: dict,
    *,
    max_attempts: int = 8,
) -> dict:
    """CAS-merge top-level stage-state keys without losing concurrent evidence."""
    if not isinstance(updates, dict):
        raise OrchestratorError("VIDEO_STAGE_STATE_INVALID", "updates must be an object")
    for _ in range(max(1, int(max_attempts))):
        job = await _crud.get_video_production_job(job_id)
        if not job:
            raise OrchestratorError("VIDEO_JOB_NOT_FOUND", job_id)
        raw = job.get("stage_state_json")
        state = _decode_stage_state(raw)
        state.update(updates)
        encoded = json.dumps(
            state, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        if await _crud.compare_and_swap_video_production_job_stage_state(
            job_id,
            expected_stage_state_json=raw,
            stage_state_json=encoded,
        ):
            return state
    raise OrchestratorError(
        "VIDEO_STAGE_STATE_CAS_CONFLICT", f"concurrent stage-state writes for {job_id}"
    )


def _released_preflight_receipt(binding: dict) -> tuple[dict, dict]:
    receipt = binding.get("bridge_lease") if isinstance(binding, dict) else None
    if not isinstance(receipt, dict):
        raise OrchestratorError(
            "BRIDGE_LINEAGE_PREFLIGHT_INVALID", "released bridge receipt missing"
        )
    project_id = str(
        binding.get("project_id") or receipt.get("flow_project_id") or ""
    ).strip()
    stable = {
        "installation_id": str(receipt.get("installation_id") or "").strip(),
        "extension_build": str(receipt.get("extension_build") or "").strip(),
        "flow_project_id": project_id,
    }
    missing = [key for key, value in stable.items() if not value]
    invalid_build = stable["extension_build"].lower() in {
        "legacy", "unknown", "n/a", "none"
    }
    if (
        missing
        or invalid_build
        or receipt.get("released") is not True
        or receipt.get("receipt_state") != "PREFLIGHT_RELEASED"
    ):
        raise OrchestratorError(
            "BRIDGE_LINEAGE_PREFLIGHT_INVALID",
            f"missing={missing} invalid_build={invalid_build} released="
            f"{receipt.get('released')!r}",
        )
    sanitized = {
        key: receipt.get(key)
        for key in _BRIDGE_RECEIPT_FIELDS
        if receipt.get(key) is not None
    }
    return stable, sanitized


def bridge_lineage_root(job: dict, *, required: bool = True) -> Optional[dict]:
    state = _decode_stage_state(job.get("stage_state_json"))
    root = state.get(BRIDGE_LINEAGE_KEY)
    if not isinstance(root, dict):
        if required:
            raise OrchestratorError(
                "BRIDGE_LINEAGE_ROOT_REQUIRED", str(job.get("job_id") or "")
            )
        return None
    if root.get("version") != BRIDGE_LINEAGE_VERSION:
        raise OrchestratorError(
            "BRIDGE_LINEAGE_VERSION_MISMATCH", str(root.get("version"))
        )
    missing = [key for key in _BRIDGE_ROOT_FIELDS if not root.get(key)]
    if missing:
        raise OrchestratorError(
            "BRIDGE_LINEAGE_ROOT_INCOMPLETE", ",".join(missing)
        )
    return dict(root)


async def persist_bridge_lineage_root(job_id: str, binding: dict) -> dict:
    """Persist one immutable installation/build/project root before paid work."""
    stable, receipt = _released_preflight_receipt(binding)
    for _ in range(8):
        job = await _crud.get_video_production_job(job_id)
        if not job:
            raise OrchestratorError("VIDEO_JOB_NOT_FOUND", job_id)
        raw = job.get("stage_state_json")
        state = _decode_stage_state(raw)
        current = state.get(BRIDGE_LINEAGE_KEY)
        if current is not None and not isinstance(current, dict):
            raise OrchestratorError(
                "BRIDGE_LINEAGE_ROOT_INVALID", "persisted root is not an object"
            )
        if isinstance(current, dict):
            root = dict(current)
            if root.get("version") != BRIDGE_LINEAGE_VERSION:
                raise OrchestratorError(
                    "BRIDGE_LINEAGE_VERSION_MISMATCH", str(root.get("version"))
                )
            mismatch = {
                key: {"expected": root.get(key), "observed": stable[key]}
                for key in _BRIDGE_ROOT_FIELDS
                if str(root.get(key) or "") != stable[key]
            }
            if mismatch:
                raise OrchestratorError(
                    "BRIDGE_LINEAGE_ROOT_MISMATCH", json.dumps(mismatch, sort_keys=True)
                )
        else:
            root = {
                "version": BRIDGE_LINEAGE_VERSION,
                **stable,
                "initial_preflight_receipt": receipt,
                "phases": {},
            }
        if job.get("project_id") and str(job["project_id"]) != stable["flow_project_id"]:
            raise OrchestratorError(
                "BRIDGE_LINEAGE_PROJECT_MISMATCH",
                f"{job.get('project_id')}!={stable['flow_project_id']}",
            )
        state[BRIDGE_LINEAGE_KEY] = root
        encoded = json.dumps(
            state, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        if await _crud.compare_and_swap_video_production_job_stage_state(
            job_id,
            expected_stage_state_json=raw,
            stage_state_json=encoded,
        ):
            if not job.get("project_id"):
                await _crud.update_video_production_job_full(
                    job_id, project_id=stable["flow_project_id"]
                )
            return root
    raise OrchestratorError(
        "VIDEO_STAGE_STATE_CAS_CONFLICT", f"could not persist bridge root for {job_id}"
    )


async def bind_bridge_lineage_initial_lane(
    job_id: str,
    *,
    lane_job_id: str,
    project_id: str,
) -> dict:
    """Bind the accepted inner lane handle once without replacing another child."""
    for _ in range(8):
        job = await _crud.get_video_production_job(job_id)
        if not job:
            raise OrchestratorError("VIDEO_JOB_NOT_FOUND", job_id)
        raw = job.get("stage_state_json")
        state = _decode_stage_state(raw)
        root = bridge_lineage_root(job)
        if str(root["flow_project_id"]) != str(project_id):
            raise OrchestratorError(
                "BRIDGE_LINEAGE_PROJECT_MISMATCH",
                f"{root['flow_project_id']}!={project_id}",
            )
        existing = str(root.get("initial_lane_job_id") or "")
        if existing and existing != str(lane_job_id):
            raise OrchestratorError(
                "BRIDGE_LINEAGE_INITIAL_LANE_MISMATCH",
                f"{existing}!={lane_job_id}",
            )
        root["initial_lane_job_id"] = str(lane_job_id)
        state[BRIDGE_LINEAGE_KEY] = root
        encoded = json.dumps(
            state, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        if await _crud.compare_and_swap_video_production_job_stage_state(
            job_id,
            expected_stage_state_json=raw,
            stage_state_json=encoded,
        ):
            return root
    raise OrchestratorError(
        "VIDEO_STAGE_STATE_CAS_CONFLICT", f"could not bind initial lane for {job_id}"
    )


async def _record_bridge_phase(job_id: str, phase: str, receipt: dict) -> None:
    for _ in range(8):
        job = await _crud.get_video_production_job(job_id)
        if not job:
            raise OrchestratorError("VIDEO_JOB_NOT_FOUND", job_id)
        raw = job.get("stage_state_json")
        state = _decode_stage_state(raw)
        root = bridge_lineage_root(job)
        phases = dict(root.get("phases") or {})
        phases[str(phase)] = dict(receipt)
        root["phases"] = phases
        state[BRIDGE_LINEAGE_KEY] = root
        encoded = json.dumps(
            state, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        if await _crud.compare_and_swap_video_production_job_stage_state(
            job_id,
            expected_stage_state_json=raw,
            stage_state_json=encoded,
        ):
            return
    raise OrchestratorError(
        "VIDEO_STAGE_STATE_CAS_CONFLICT", f"could not persist phase {phase}"
    )


def _production_bridge_client(client: Any) -> bool:
    from agent.services.flow_client import FlowClient

    return isinstance(client, FlowClient)


async def bridge_lineage_phase(
    client: Any,
    job_id: str,
    phase: str,
    action: BridgePhaseFn,
) -> Any:
    """Run one provider-facing phase on a freshly challenged rooted lease.

    Small non-FlowClient unit doubles remain an explicit provider-free seam.
    Production ``FlowClient`` instances cannot bypass the persisted root.
    """
    if not _production_bridge_client(client):
        return await action(None)

    job = await _crud.get_video_production_job(job_id)
    if not job:
        raise OrchestratorError("VIDEO_JOB_NOT_FOUND", job_id)
    root = bridge_lineage_root(job)
    lease_methods = (
        "acquire_operation_lease",
        "activate_operation_lease",
        "release_operation_lease",
    )
    if not all(callable(getattr(client, name, None)) for name in lease_methods):
        raise OrchestratorError(
            "BRIDGE_LINEAGE_LEASE_API_UNAVAILABLE", client.__class__.__name__
        )

    lease = None
    bound_receipt = None
    released = False
    try:
        lease = client.acquire_operation_lease(
            installation_id=str(root["installation_id"])
        )
        with client.activate_operation_lease(lease):
            from agent.services import make_video as _mv

            binding = await _mv._bind_editor_session(
                client,
                str(root["flow_project_id"]),
                bridge_lease=lease,
            )
            lease = dict(binding.get("bridge_lease") or {})
            observed = {
                "installation_id": str(lease.get("installation_id") or ""),
                "extension_build": str(lease.get("extension_build") or ""),
                "flow_project_id": str(
                    binding.get("project_id") or lease.get("flow_project_id") or ""
                ),
            }
            mismatch = {
                key: {"expected": root[key], "observed": observed[key]}
                for key in _BRIDGE_ROOT_FIELDS
                if str(root[key]) != observed[key]
            }
            if mismatch:
                raise OrchestratorError(
                    "BRIDGE_LINEAGE_PHASE_MISMATCH", json.dumps(mismatch, sort_keys=True)
                )
            bound_receipt = {
                key: lease.get(key)
                for key in _BRIDGE_RECEIPT_FIELDS
                if lease.get(key) is not None
            }
            bound_receipt.update(
                {
                    "state": "BOUND",
                    "phase": str(phase),
                    "flow_project_id": observed["flow_project_id"],
                }
            )
            await _record_bridge_phase(job_id, phase, bound_receipt)
            return await action(binding)
    finally:
        # This synchronous release is deliberately the first cleanup operation:
        # cancellation or a failed evidence write cannot strand connection ownership.
        if lease is not None:
            try:
                released = bool(client.release_operation_lease(lease))
            except Exception:  # noqa: BLE001 — evidence below records the failure
                released = False
        if bound_receipt is not None:
            release_receipt = {
                **bound_receipt,
                "state": "RELEASED" if released else "RELEASE_FAILED",
                "released": released,
                "released_at": time.time(),
            }
            try:
                await _record_bridge_phase(job_id, phase, release_receipt)
            except Exception:  # noqa: BLE001 — never mask the provider/action result
                pass


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
    prepare_initial: Optional[InitialPrepareFn] = None,
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
    # A final render can be durable while the local library write was
    # interrupted. Repair only that local delivery boundary; never re-enter a
    # provider submit just because the artifact row is missing.
    if job.get("final_media_id") and job.get("final_local_path"):
        existing_artifact = await _crud.get_generated_artifact(job["final_media_id"])
        if existing_artifact is None:
            try:
                from agent.services.video_artifact_delivery_service import (
                    register_final_video_artifact,
                )

                await register_final_video_artifact(
                    {
                        "final_media_id": job["final_media_id"],
                        "local_path": job["final_local_path"],
                        "measured_duration_s": job.get("final_duration_s"),
                    },
                    job_id=job_id,
                    mode="EXTEND",
                    project_id=job.get("project_id"),
                    product_id=job.get("product_id"),
                )
                await _crud.update_video_production_job_full(
                    job_id, status=S_COMPLETE, error_code=None
                )
                job = await _crud.get_video_production_job(job_id)
            except Exception as exc:  # noqa: BLE001 — remain retryable, not green
                await _crud.update_video_production_job_full(
                    job_id, status=F_FINAL_ARTIFACT, error_code=F_FINAL_ARTIFACT
                )
                return await get_job_status(job_id)
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

            # The zero-credit editor preflight and immutable root persistence must
            # finish before INITIAL ownership is reserved.  If this await is
            # interrupted there is still no side-effect row to strand in an
            # unsubmitted RESUME_ONLY state; re-entry can safely start again.
            callback_job = job
            if prepare_initial is not None:
                try:
                    preflight = await prepare_initial(job)
                except Exception as exc:  # noqa: BLE001 — provider-free, retryable
                    await _crud.update_video_production_job_full(
                        job_id, status=F_INITIAL, error_code=F_INITIAL
                    )
                    raise OrchestratorError(F_INITIAL, str(exc)[:200]) from exc
                refreshed = await _crud.get_video_production_job(job_id)
                if not refreshed:
                    raise OrchestratorError("VIDEO_JOB_NOT_FOUND", job_id)
                callback_job = {
                    **refreshed,
                    "_bridge_lineage_preflight": preflight,
                }

            async def _run_initial(_binding):
                bal_before = await _safe_credits(client)
                claim = await _crud.claim_safe_video_job_side_effect_submission(
                    idem,
                    job_id=job_id,
                    stage="INITIAL",
                    expected_submit_count=int(
                        (existing or {}).get("effective_submit_count") or 0
                    ),
                    credit_balance_before=bal_before,
                )
                if not claim["claimed"]:
                    # A concurrent caller crossed the exact submit boundary first,
                    # or the durable row is not provably SAFE. Resume only.
                    return await _drive_initial_resume(
                        job_id, idem, resume_initial, client
                    )
                await _crud.update_video_production_job_full(
                    job_id, status=S_INITIAL_SUBMITTING
                )
                try:
                    seg = await generate_initial(callback_job)
                except Exception as exc:  # noqa: BLE001
                    # The one-door lane persists its handle immediately after an
                    # accepted submit. No handle (or a proven zero-credit rejection)
                    # remains SAFE; an accepted unknown child remains BLOCKED.
                    fresh = await _crud.get_video_production_job(job_id) or {}
                    _err_text = str(exc)
                    _zero_credit = any(
                        sig in _err_text for sig in ZERO_CREDIT_REJECTION_SIGNATURES
                    )
                    if (
                        not str(fresh.get("initial_lane_job_id") or "").strip()
                        or _zero_credit
                    ):
                        await _crud.update_video_job_side_effect(
                            idem, submission_state=SUB_NOT_ATTEMPTED,
                            credit_state=CR_NOT_SPENT, retry_safety=RS_SAFE,
                            detail=str(exc)[:200])
                    else:
                        await _crud.update_video_job_side_effect(
                            idem, submission_state=SUB_UNCERTAIN,
                            credit_state=CR_MAY_HAVE_SPENT,
                            retry_safety=RS_BLOCKED, detail=str(exc)[:200])
                    await _crud.update_video_production_job_full(
                        job_id, status=F_INITIAL, error_code=F_INITIAL)
                    raise OrchestratorError(F_INITIAL, str(exc)[:200]) from exc
                await _persist_initial_result(
                    job_id, idem, seg, bal_before=bal_before, client=client
                )

            initial_result = await bridge_lineage_phase(
                client, job_id, "INITIAL", _run_initial
            )
            job = await _crud.get_video_production_job(job_id)
            if not job.get("initial_operation_id"):
                return initial_result
        else:
            # ALREADY SUBMITTED (this run or a crashed prior run) — resume poll-only.
            if existing.get("submission_state") == SUB_UNCERTAIN:
                # already reconciled to RECOVERY/failed — surface, never resubmit
                return await get_job_status(job_id)
            async def _resume_initial(_binding):
                return await _drive_initial_resume(
                    job_id, idem, resume_initial, client
                )

            resumed = await bridge_lineage_phase(
                client, job_id, "INITIAL_RESUME", _resume_initial
            )
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
                project_id=job["project_id"], product_id=job.get("product_id"),
                scene_id=job["scene_id"],
                source_operation_id=parent_op, blocks=blocks,
                aspect_ratio=extend_aspect_ratio(job.get("aspect_ratio")))
            try:
                async def _run_extend(_binding):
                    return await _nx.run_native_extend_chain(
                        client, req, dry_run=False, confirm_live_credit_burn=True,
                        confirmed_extend_operation_count=1)

                result = await bridge_lineage_phase(
                    client, job_id, f"EXTEND_{position}", _run_extend
                )
            except Exception as exc:  # noqa: BLE001
                # Credit honesty: classify by whether the generate_video_extend RPC
                # was reached (provider touched). A POST-RPC failure code — or a
                # submit/timeout error — means a credit-bearing child MAY have
                # started, so it is UNCERTAIN / MAY_HAVE_SPENT / BLOCKED (never
                # auto-SAFE). Only PRE-RPC contract/validation failures stay SAFE.
                _code = getattr(exc, "code", "") or ""
                provider_touched = (
                    _code in _EXTEND_POST_RPC_CODES
                    or "SUBMIT" in str(exc).upper() or "TIMEOUT" in str(exc).upper()
                )
                await _crud.update_video_job_side_effect(
                    idem,
                    submission_state=(SUB_UNCERTAIN if provider_touched else SUB_NOT_ATTEMPTED),
                    credit_state=(CR_MAY_HAVE_SPENT if provider_touched else CR_NOT_SPENT),
                    retry_safety=(RS_BLOCKED if provider_touched else RS_SAFE),
                    detail=str(exc)[:200])
                await _crud.update_video_production_job_full(
                    job_id, status=F_EXTEND, error_code=F_EXTEND)
                raise OrchestratorError(F_EXTEND, str(exc)[:200]) from exc
            child = (result.get("blocks") or [{}])[-1]
            child_op = child.get("child_operation_id")
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
            else:
                native_idem = _nx._idempotency_key(
                    str(job.get("project_id") or ""),
                    str(job.get("scene_id") or ""),
                    position,
                    _nx._prompt_hash(prompt),
                    parent_op,
                )
                lineage = await _crud.get_extend_lineage_by_idempotency(native_idem)
                if lineage and lineage.get("polling_state") in {
                    _nx.STATE_SUBMITTED,
                    _nx.STATE_POLLING,
                    _nx.STATE_HARVEST_FAILED,
                    _nx.STATE_SUCCEEDED,
                }:
                    try:
                        async def _resume_extend(_binding):
                            return await _nx.resume_known_extend_child(
                                client,
                                lineage_id=lineage["extend_lineage_id"],
                                poll_interval_s=poll_interval_s,
                            )

                        child = await bridge_lineage_phase(
                            client,
                            job_id,
                            f"EXTEND_{position}_RESUME",
                            _resume_extend,
                        )
                    except Exception as exc:  # noqa: BLE001 — never resubmit
                        await _crud.update_video_job_side_effect(
                            idem,
                            submission_state=SUB_UNCERTAIN,
                            credit_state=CR_MAY_HAVE_SPENT,
                            retry_safety=RS_BLOCKED,
                            detail=str(exc)[:200],
                        )
                        await _crud.update_video_production_job_full(
                            job_id, status=F_EXTEND, error_code=F_EXTEND
                        )
                        raise OrchestratorError(F_EXTEND, str(exc)[:200]) from exc
                    child_op = child.get("child_operation_id")
                    if not child_op:
                        raise OrchestratorError(
                            F_EXTEND, "known Extend lineage returned no child operation"
                        )
                    segs = segments + [child_op]
                    await _crud.update_video_production_job_full(
                        job_id,
                        status=S_EXTEND_READY,
                        extend_child_operation_id=child_op,
                        extend_child_workflow_id=child.get("child_workflow_id"),
                        segment_media_ids_json=json.dumps(segs),
                    )
                    await _crud.update_video_job_side_effect(
                        idem,
                        submission_state=SUB_TERMINAL,
                        credit_state=CR_MAY_HAVE_SPENT,
                        retry_safety=RS_RESUME_ONLY,
                        operation_ref=child_op,
                    )
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
            refreshed = await _crud.get_video_production_job(job_id) or job
            if refreshed.get("final_media_id"):
                return await get_job_status(job_id)
            # A concat is already owned by another caller/process. The final
            # timeline runtime can resume polling only when its provider job
            # name was durably captured. If it was not captured, do not guess
            # or re-submit: leave the record visible for reconciliation.
            if not refreshed.get("final_concat_job_name"):
                return await get_job_status(job_id)
            job = refreshed
        if r["reserved"]:
            await _crud.increment_side_effect_submit_count(idem)
            await _crud.update_video_job_side_effect(
                idem, submission_state=SUB_SUBMITTED, credit_state=CR_UNKNOWN,
                retry_safety=RS_RESUME_ONLY)
        try:
            async def _run_concat(_binding):
                return await _ft.finalize_timeline(
                    client, job_id=job_id, segment_media_ids=segments,
                    requested_seconds=int(job.get("requested_duration_seconds") or 16),
                    out_dir=out_dir or (Path("output") / "retrieved"),
                    dry_run=False, confirm_live_credit_burn=True,
                    poll_interval_s=poll_interval_s)

            done = await bridge_lineage_phase(
                client, job_id, "CONCAT", _run_concat
            )
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
        try:
            from agent.services.video_artifact_delivery_service import (
                register_final_video_artifact,
            )

            await register_final_video_artifact(
                done,
                job_id=job_id,
                mode="EXTEND",
                project_id=job.get("project_id"),
                product_id=job.get("product_id"),
            )
        except Exception as exc:  # noqa: BLE001 — provider output is not delivery
            await _crud.update_video_production_job_full(
                job_id, status=F_FINAL_ARTIFACT, error_code=F_FINAL_ARTIFACT
            )
            raise OrchestratorError(F_FINAL_ARTIFACT, str(exc)[:200]) from exc

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
    F_FINAL_ARTIFACT: "The final video rendered, but its local delivery needs retry.",
    F_AUTH: "Please review and confirm the video again.",
}


def _human_stage(status: Optional[str]) -> str:
    return _HUMAN.get(status or "", "Preparing video")


async def contain_restart_recovery_jobs(
    job_ids: list[str],
    *,
    authorized_by: str,
    authorization_note: str,
) -> dict[str, Any]:
    """Revoke exact startup-recovery authorizations without touching side effects.

    The operation is all-or-nothing. It refuses jobs with a provider operation
    reference because an unknown operation must not be concealed by this narrow
    owner hold. Re-applying the same containment is an idempotent readback.
    """

    resolved_job_ids = [str(job_id).strip() for job_id in job_ids if str(job_id).strip()]
    if not resolved_job_ids or len(set(resolved_job_ids)) != len(resolved_job_ids):
        raise OrchestratorError(
            "INVALID_RECOVERY_CONTAINMENT_SCOPE",
            "job_ids must be non-empty and unique",
        )
    resolved_authorized_by = str(authorized_by or "").strip()
    resolved_note = str(authorization_note or "").strip()
    if not resolved_authorized_by or not resolved_note:
        raise OrchestratorError(
            "RECOVERY_CONTAINMENT_AUTHORITY_REQUIRED",
            "authorized_by and authorization_note are required",
        )

    mutation_records: list[dict[str, Any]] = []
    readbacks: list[dict[str, Any]] = []
    effect_snapshots: dict[str, list[dict]] = {}
    contained_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    for job_id in resolved_job_ids:
        job = await _crud.get_video_production_job(job_id)
        if not job:
            raise OrchestratorError("VIDEO_JOB_NOT_FOUND", job_id)
        raw_stage_state = job.get("stage_state_json")
        if raw_stage_state:
            try:
                stage_state = json.loads(raw_stage_state)
            except (TypeError, ValueError) as exc:
                raise OrchestratorError(
                    "INVALID_RECOVERY_AUDIT_STATE",
                    job_id,
                ) from exc
            if not isinstance(stage_state, dict):
                raise OrchestratorError("INVALID_RECOVERY_AUDIT_STATE", job_id)
        else:
            stage_state = {}

        effects = await _crud.list_video_job_side_effects(job_id)
        effect_snapshots[job_id] = effects
        if any(str(effect.get("operation_ref") or "").strip() for effect in effects):
            raise OrchestratorError(
                "RECOVERY_CONTAINMENT_OPERATION_REF_PRESENT",
                job_id,
            )

        existing_hold = stage_state.get("owner_recovery_hold")
        if job.get("authorization_token") is None:
            if not isinstance(existing_hold, dict):
                raise OrchestratorError(
                    "RECOVERY_CONTAINMENT_AUTHORIZATION_ALREADY_ABSENT",
                    job_id,
                )
            readbacks.append(
                {
                    "job_id": job_id,
                    "changed": False,
                    "status_before": job.get("status"),
                    "status_after": job.get("status"),
                    "error_code_before": job.get("error_code"),
                    "error_code_after": job.get("error_code"),
                    "authorization_present_before": False,
                    "authorization_present_after": False,
                    "owner_recovery_hold": existing_hold,
                    "side_effect_count": len(effects),
                }
            )
            continue

        if job.get("status") not in {S_AUTHORIZED, S_AUTH_EXPIRED}:
            raise OrchestratorError(
                "RECOVERY_CONTAINMENT_UNSUPPORTED_STATUS",
                f"{job_id}:{job.get('status')}",
            )

        hold = {
            "version": OWNER_RECOVERY_HOLD_VERSION,
            "authorized_by": resolved_authorized_by,
            "authorization_note": resolved_note,
            "contained_at": contained_at,
            "prior_status": job.get("status"),
            "prior_error_code": job.get("error_code"),
            "authorization_revoked": True,
            "provider_polling_allowed": False,
            "generation_resubmission_allowed": False,
            "side_effect_ledger_preserved": True,
        }
        stage_state["owner_recovery_hold"] = hold
        next_error = (
            job.get("error_code")
            if job.get("status") == S_AUTH_EXPIRED and job.get("error_code")
            else OWNER_RECOVERY_HOLD_CODE
        )
        mutation_records.append(
            {
                "job_id": job_id,
                "status": S_AUTH_EXPIRED,
                "error_code": next_error,
                "stage_state_json": json.dumps(
                    stage_state,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                "expected_status": job.get("status"),
                "expected_authorization_token": job.get("authorization_token"),
                "expected_stage_state_json": raw_stage_state,
            }
        )
        readbacks.append(
            {
                "job_id": job_id,
                "changed": True,
                "status_before": job.get("status"),
                "status_after": S_AUTH_EXPIRED,
                "error_code_before": job.get("error_code"),
                "error_code_after": next_error,
                "authorization_present_before": True,
                "authorization_present_after": False,
                "owner_recovery_hold": hold,
                "side_effect_count": len(effects),
            }
        )

    changed_count = await _crud.contain_video_production_jobs_for_restart(
        mutation_records
    )
    for item in readbacks:
        job_id = str(item["job_id"])
        after = await _crud.get_video_production_job(job_id)
        if not after or after.get("authorization_token") is not None:
            raise OrchestratorError("RECOVERY_CONTAINMENT_READBACK_FAILED", job_id)
        if await _crud.list_video_job_side_effects(job_id) != effect_snapshots[job_id]:
            raise OrchestratorError(
                "RECOVERY_CONTAINMENT_SIDE_EFFECT_DRIFT",
                job_id,
            )
        item["status_after"] = after.get("status")
        item["error_code_after"] = after.get("error_code")

    return {
        "changed_count": changed_count,
        "jobs": readbacks,
        "startup_recovery_candidates_remaining": len(
            await _crud.list_non_terminal_authorized_jobs()
        ),
    }


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
