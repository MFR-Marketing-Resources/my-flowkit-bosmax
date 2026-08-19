"""Final Prompt Approval Gate — per-dispatch WYSIWYG execution approval.

Governing invariant (locked architecture 2026-08-19):

    WHAT THE USER REVIEWED & APPROVED  ==  WHAT BOSMAX ACTUALLY DISPATCHED

proven at the real provider dispatch boundary by

    approved_prompt_sha256            == dispatched_prompt_sha256
    approved_execution_envelope_sha256 == dispatched_execution_envelope_sha256

This module owns the shared per-dispatch approval primitive used by every active
generation surface (Hybrid / Faceless / Montage / Production Studio / Poster
Builder) and by the backend dispatch choke points. It freezes the FINAL,
provider-ready execution envelope (prompt + resolved assets + genuinely
provider-affecting settings) at human-review time, and the dispatch boundary
verifies the live envelope against an APPROVED snapshot.

Design notes:
  * Snapshot approval is a DIFFERENT, finer layer than the product/mode-level
    ``production_prompt_approval_service`` (which stays as-is). This gate is
    per-generation/per-dispatch. The two compose; this one never forks the
    product-level status.  See project_final_prompt_approval_gate_architecture.
  * The execution envelope contains ONLY provider-affecting fields the dispatch
    path actually consumes (``make_video.start_generate`` signature: mode,
    prompt, image_media_ids, aspect, model, duration_s, num_videos, image_model,
    source_mode). ``seed`` is NOT a runtime input, so it is deliberately absent —
    no invented fields.
  * The manual-edit safety scan reuses the existing non-mutating
    ``production_prompt_approval_service.scan_prompt_text`` — never a new scrub.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any

from agent.db import execution_approval_crud as _crud
from agent.services.production_prompt_approval_service import scan_prompt_text


class ApprovalState:
    """The per-dispatch approval lifecycle (string state machine)."""

    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    EDITED = "EDITED"
    APPROVED = "APPROVED"
    INVALIDATED = "INVALIDATED"
    DISPATCHED = "DISPATCHED"


# Only APPROVED snapshots may authorise a dispatch. A DISPATCHED snapshot is
# single-use (already bound to a provider job); it never re-authorises.
_APPROVABLE_FROM = {ApprovalState.REVIEW_REQUIRED, ApprovalState.EDITED}
_INVALIDATABLE_FROM = {
    ApprovalState.REVIEW_REQUIRED,
    ApprovalState.EDITED,
    ApprovalState.APPROVED,
}


class ExecutionApprovalError(Exception):
    """Raised when a dispatch is not covered by a valid APPROVED snapshot.

    Fail-closed: the dispatch boundary must never spend a credit on an
    unverified envelope.
    """

    def __init__(self, code: str, message: str, *, status_code: int = 409,
                 details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def gate_enforced() -> bool:
    """Whether the dispatch boundary HARD-BLOCKS unapproved credit-bearing spend.

    Default OFF for safe rollout: the snapshot lifecycle and verification run and
    are recorded regardless, but hard blocking is only active once the operator
    surfaces that create snapshots are live and the flag is set. When OFF the
    boundary still records an audit verdict (observe-only) and never blocks.
    """
    return str(os.environ.get("EXECUTION_APPROVAL_GATE_ENFORCED", "")).strip().lower() in {
        "1", "true", "yes", "on",
    }


# --------------------------------------------------------------------------- #
# Exhaustive provider-boundary backstop
# --------------------------------------------------------------------------- #
# The dispatch-lane gate (verify_and_bind_dispatch) covers start_generate,
# Native Extend and Direct Capture. But several low-level provider paths reach a
# credit-bearing FlowClient method WITHOUT crossing those lanes. The single layer
# EVERY credit-bearing dispatch crosses is the FlowClient provider method itself,
# so a thin authorisation backstop sits there and closes every video-credit leak.
#
# Authorisation flows implicitly: verify_and_bind_dispatch, on a PASS, marks the
# CURRENT async context authorised; ``asyncio.create_task`` copies that context,
# so the downstream FlowClient call inherits it. A legitimate non-lane path may
# mark itself EXEMPT (documented) instead. When enforcement is OFF the backstop
# is inert (never blocks).

_DISPATCH_AUTH: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "bosmax_dispatch_authorization", default=None,
)


def current_dispatch_authorization() -> dict | None:
    return _DISPATCH_AUTH.get()


def mark_dispatch_exempt(reason: str) -> None:
    """Mark the current async context as an intentional, non-approval provider
    dispatch (assembly/recovery/dev). Documented and auditable; never silent."""
    _DISPATCH_AUTH.set({"kind": "EXEMPT", "reason": _norm(reason) or "EXEMPT"})


def video_dispatch_unauthorized_reason(*, method: str) -> str | None:
    """Backstop for the FlowClient provider boundary. When
    EXECUTION_APPROVAL_GATE_ENFORCED, a credit-bearing VIDEO call is refused
    unless the current async context carries an APPROVED dispatch (from a passed
    dispatch-lane gate) or an explicit EXEMPT marker. Returns a block-reason
    string, or None when allowed.

    Non-raising by design: FlowClient._send has a never-raise contract, so it
    turns this into an ``{"error": ...}`` result. Inert when enforcement is off."""
    if not gate_enforced():
        return None
    if _DISPATCH_AUTH.get():
        return None
    return "PROVIDER_DISPATCH_UNAUTHORIZED"


# --------------------------------------------------------------------------- #
# Deterministic envelope + hashing (single source used at BOTH review + dispatch)
# --------------------------------------------------------------------------- #

def _stable_json(value: Any) -> str:
    """Deterministic JSON (sorted keys, compact) — same convention as the P6
    ``_payload_hash`` primitive, so hashes are stable across processes."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _norm(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def compute_dispatch_identity(
    *,
    mode: str,
    final_prompt_text: str,
    source_mode: str | None = None,
    model: str | None = None,
    aspect: str | None = None,
    duration_s: int | None = None,
    count: int | None = None,
    image_model: str | None = None,
    asset_media_ids: list[str] | None = None,
) -> dict[str, Any]:
    """THE canonical envelope+hash builder. Called with identical semantics at
    review time and at the dispatch boundary, so equal provider-affecting inputs
    always yield equal hashes.

    Returns ``{prompt_sha256, execution_envelope, execution_envelope_sha256}``.
    The envelope keys are a fixed shape; unused fields normalise to ``None`` and
    still participate in the hash, so adding/removing a provider-affecting field
    later is an explicit, versioned change — never silent.
    """
    prompt_text = final_prompt_text or ""
    prompt_sha256 = _sha256_text(prompt_text)

    def _int_or_none(v: Any) -> int | None:
        if v in (None, ""):
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    envelope = {
        "envelope_version": 1,
        "mode": _norm(mode).upper(),
        "prompt_sha256": prompt_sha256,
        "source_mode": (_norm(source_mode).upper() or None),
        "model": (_norm(model) or None),
        "aspect": (_norm(aspect) or None),
        "duration_s": _int_or_none(duration_s),
        "count": _int_or_none(count),
        "image_model": (_norm(image_model) or None),
        # Resolved reference asset identity. Sorted + de-duped so ordering never
        # changes the hash. A self-heal re-upload that swaps a media id IS an
        # asset change here — it correctly invalidates the approval (contract:
        # "asset changed -> INVALIDATED -> REVIEW_REQUIRED").
        "asset_fingerprints": sorted({_norm(m) for m in (asset_media_ids or []) if _norm(m)}),
    }
    return {
        "prompt_sha256": prompt_sha256,
        "execution_envelope": envelope,
        "execution_envelope_sha256": hashlib.sha256(
            _stable_json(envelope).encode("utf-8")
        ).hexdigest(),
    }


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #

async def create_review_snapshot(
    *,
    surface: str,
    logical_mode: str,
    final_prompt_text: str,
    product_id: str | None = None,
    source_mode: str | None = None,
    model: str | None = None,
    aspect: str | None = None,
    duration_s: int | None = None,
    count: int | None = None,
    image_model: str | None = None,
    asset_media_ids: list[str] | None = None,
    review_session_id: str | None = None,
    created_by: str | None = None,
) -> dict[str, Any]:
    """Freeze a FINAL provider-ready envelope for human review (REVIEW_REQUIRED).

    ``final_prompt_text`` MUST already be the fully grounded, provider-ready
    prompt (product-truth / grounding / safety / asset-resolution applied
    BEFORE review — never after approval)."""
    identity = compute_dispatch_identity(
        mode=logical_mode,
        final_prompt_text=final_prompt_text,
        source_mode=source_mode,
        model=model,
        aspect=aspect,
        duration_s=duration_s,
        count=count,
        image_model=image_model,
        asset_media_ids=asset_media_ids,
    )
    scan = scan_prompt_text(final_prompt_text, product_id=product_id)
    scan_clean = not any(scan.values())
    now = _now()
    snapshot_id = "eas_" + uuid.uuid4().hex[:16]
    row = {
        "snapshot_id": snapshot_id,
        "review_session_id": review_session_id or ("rev_" + uuid.uuid4().hex[:12]),
        "product_id": product_id,
        "surface": _norm(surface),
        "logical_mode": _norm(logical_mode).upper(),
        "source_mode": (_norm(source_mode).upper() or None),
        "final_prompt_text": final_prompt_text or "",
        "prompt_sha256": identity["prompt_sha256"],
        "execution_envelope_json": _stable_json(identity["execution_envelope"]),
        "execution_envelope_sha256": identity["execution_envelope_sha256"],
        "approval_state": ApprovalState.REVIEW_REQUIRED,
        "edited": 0,
        "scan_clean": 1 if scan_clean else 0,
        "scan_json": _stable_json(scan),
        "approved_version": 0,
        "approved_by": None,
        "approved_at": None,
        "approved_prompt_sha256": None,
        "approved_execution_envelope_sha256": None,
        "invalidation_reason": None,
        "dispatched_prompt_sha256": None,
        "dispatched_execution_envelope_sha256": None,
        "provider_job_id": None,
        "dispatched_at": None,
        "created_by": (_norm(created_by) or None),
        "created_at": now,
        "updated_at": now,
    }
    return await _crud.create_snapshot(row)


async def apply_edit(
    snapshot_id: str,
    *,
    edited_prompt_text: str,
    editor_id: str | None = None,
) -> dict[str, Any]:
    """Operator edited the provider-ready prompt. Re-scan (non-mutating), recompute
    the envelope hash, and return to a non-approved state (EDITED). The edited text
    can never inherit a prior clean-scan or approval."""
    snap = await _require(snapshot_id)
    if snap["approval_state"] == ApprovalState.DISPATCHED:
        raise ExecutionApprovalError(
            "SNAPSHOT_ALREADY_DISPATCHED",
            "A dispatched snapshot is immutable and cannot be edited.",
        )
    identity = _recompute_from_snapshot(snap, final_prompt_text=edited_prompt_text)
    scan = scan_prompt_text(edited_prompt_text, product_id=snap.get("product_id"))
    scan_clean = not any(scan.values())
    return await _crud.update_snapshot(
        snapshot_id,
        final_prompt_text=edited_prompt_text or "",
        prompt_sha256=identity["prompt_sha256"],
        execution_envelope_json=_stable_json(identity["execution_envelope"]),
        execution_envelope_sha256=identity["execution_envelope_sha256"],
        approval_state=ApprovalState.EDITED,
        edited=1,
        scan_clean=1 if scan_clean else 0,
        scan_json=_stable_json(scan),
        # An edit clears any prior approval freeze.
        approved_by=None,
        approved_at=None,
        approved_prompt_sha256=None,
        approved_execution_envelope_sha256=None,
        invalidation_reason=None,
        updated_at=_now(),
    )


async def approve_snapshot(
    snapshot_id: str,
    *,
    approved_by: str,
) -> dict[str, Any]:
    """Human approval. Requires a clean safety scan. Freezes the approved prompt
    and execution-envelope SHAs — these become the equality target at dispatch."""
    snap = await _require(snapshot_id)
    if snap["approval_state"] not in _APPROVABLE_FROM:
        raise ExecutionApprovalError(
            "SNAPSHOT_NOT_APPROVABLE",
            f"Snapshot in state {snap['approval_state']} cannot be approved.",
            details={"state": snap["approval_state"]},
        )
    if not int(snap.get("scan_clean") or 0):
        raise ExecutionApprovalError(
            "SNAPSHOT_SCAN_NOT_CLEAN",
            "The prompt failed the safety scan; approval is refused.",
            details={"scan": json.loads(snap.get("scan_json") or "{}")},
        )
    now = _now()
    return await _crud.update_snapshot(
        snapshot_id,
        approval_state=ApprovalState.APPROVED,
        approved_version=int(snap.get("approved_version") or 0) + 1,
        approved_by=_norm(approved_by) or "operator",
        approved_at=now,
        approved_prompt_sha256=snap["prompt_sha256"],
        approved_execution_envelope_sha256=snap["execution_envelope_sha256"],
        invalidation_reason=None,
        updated_at=now,
    )


async def invalidate_snapshot(
    snapshot_id: str,
    *,
    reason: str,
) -> dict[str, Any]:
    """Invalidate an approval (a provider-affecting change was detected, or an
    operator withdrew it). Returns the snapshot to REVIEW_REQUIRED."""
    snap = await _require(snapshot_id)
    if snap["approval_state"] not in _INVALIDATABLE_FROM:
        return snap
    now = _now()
    return await _crud.update_snapshot(
        snapshot_id,
        approval_state=ApprovalState.INVALIDATED,
        approved_prompt_sha256=None,
        approved_execution_envelope_sha256=None,
        invalidation_reason=_norm(reason) or "INVALIDATED",
        updated_at=now,
    )


async def ensure_upstream_approved_snapshot(
    *,
    mode: str,
    final_prompt_text: str,
    surface: str,
    provenance: str,
    product_id: str | None = None,
    source_mode: str | None = None,
    model: str | None = None,
    aspect: str | None = None,
    duration_s: int | None = None,
    count: int | None = None,
    image_model: str | None = None,
    asset_media_ids: list[str] | None = None,
    approved_by: str = "system:upstream-approval",
) -> dict[str, Any]:
    """Materialise an APPROVED snapshot for a NON-UI dispatch that fires an
    already-approved package/plan (Production Queue, bulk, Production Studio
    scheduler, Extend). The human review happened UPSTREAM at package/plan
    approval; this records that lineage (``provenance`` -> ``created_by``) so the
    enforced dispatch boundary passes for legitimately-approved production runs.

    Fail-closed guarantees preserved:
      * Idempotent by envelope — reuses an existing APPROVED snapshot.
      * A dirty prompt (failed safety scan) is NEVER auto-approved; it stays
        REVIEW_REQUIRED so the dispatch blocks.
      * Callers MUST pass this ONLY when a real upstream approval exists (e.g.
        production_status == APPROVED). A path with no upstream approval must not
        call it — that dispatch remains fail-closed.
    """
    identity = compute_dispatch_identity(
        mode=mode,
        final_prompt_text=final_prompt_text,
        source_mode=source_mode,
        model=model,
        aspect=aspect,
        duration_s=duration_s,
        count=count,
        image_model=image_model,
        asset_media_ids=asset_media_ids,
    )
    existing = await _crud.find_approved_by_envelope(identity["execution_envelope_sha256"])
    if existing:
        return existing
    snap = await create_review_snapshot(
        surface=surface,
        logical_mode=mode,
        final_prompt_text=final_prompt_text,
        product_id=product_id,
        source_mode=source_mode,
        model=model,
        aspect=aspect,
        duration_s=duration_s,
        count=count,
        image_model=image_model,
        asset_media_ids=asset_media_ids,
        created_by=_norm(provenance) or "upstream-approval",
    )
    if not int(snap.get("scan_clean") or 0):
        return snap  # dirty prompt -> not approved -> dispatch stays fail-closed
    return await approve_snapshot(snap["snapshot_id"], approved_by=approved_by)


async def verify_and_bind_dispatch(
    *,
    mode: str,
    final_prompt_text: str,
    source_mode: str | None = None,
    model: str | None = None,
    aspect: str | None = None,
    duration_s: int | None = None,
    count: int | None = None,
    image_model: str | None = None,
    asset_media_ids: list[str] | None = None,
    snapshot_id: str | None = None,
    provider_job_id: str | None = None,
) -> dict[str, Any]:
    """THE dispatch-boundary gate.

    Recompute the live dispatch envelope, then require an APPROVED snapshot whose
    frozen ``approved_execution_envelope_sha256`` equals it. On match, bind the
    dispatch (state -> DISPATCHED) and return a PASS verdict. On mismatch, either
    raise (enforced) or return an observe-only FAIL verdict (rollout OFF).

    This is the single authoritative equality check behind the invariant. Every
    credit-bearing dispatch choke calls it with the SAME inputs it hands the
    provider.
    """
    identity = compute_dispatch_identity(
        mode=mode,
        final_prompt_text=final_prompt_text,
        source_mode=source_mode,
        model=model,
        aspect=aspect,
        duration_s=duration_s,
        count=count,
        image_model=image_model,
        asset_media_ids=asset_media_ids,
    )
    dispatched_env_sha = identity["execution_envelope_sha256"]
    dispatched_prompt_sha = identity["prompt_sha256"]

    match = await _crud.find_approved_by_envelope(
        dispatched_env_sha, snapshot_id=snapshot_id,
    )
    verdict = {
        "pass": bool(match),
        "enforced": gate_enforced(),
        "dispatched_prompt_sha256": dispatched_prompt_sha,
        "dispatched_execution_envelope_sha256": dispatched_env_sha,
        "snapshot_id": (match or {}).get("snapshot_id") if match else None,
        "reason": None,
    }
    if not match:
        verdict["reason"] = (
            "NO_APPROVED_SNAPSHOT_FOR_ENVELOPE"
            if snapshot_id is None
            else "SNAPSHOT_ENVELOPE_MISMATCH_OR_NOT_APPROVED"
        )
        if gate_enforced():
            raise ExecutionApprovalError(
                "DISPATCH_NOT_APPROVED",
                "This generation was not covered by a matching APPROVED "
                "execution snapshot. Review and approve the final prompt before "
                "dispatch.",
                details=verdict,
            )
        return verdict

    # Equality proven — bind the dispatch (single-use).
    now = _now()
    await _crud.update_snapshot(
        match["snapshot_id"],
        approval_state=ApprovalState.DISPATCHED,
        dispatched_prompt_sha256=dispatched_prompt_sha,
        dispatched_execution_envelope_sha256=dispatched_env_sha,
        provider_job_id=(_norm(provider_job_id) or None),
        dispatched_at=now,
        updated_at=now,
    )
    # Authorise the current async context for the downstream provider-boundary
    # backstop (copied into the generation task by asyncio.create_task).
    _DISPATCH_AUTH.set({
        "kind": "APPROVED",
        "envelope_sha256": dispatched_env_sha,
        "snapshot_id": match["snapshot_id"],
    })
    verdict["reason"] = "APPROVED_ENVELOPE_MATCH"
    return verdict


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #

async def get_snapshot(snapshot_id: str) -> dict[str, Any] | None:
    return await _crud.get_snapshot(snapshot_id)


async def _require(snapshot_id: str) -> dict[str, Any]:
    snap = await _crud.get_snapshot(snapshot_id)
    if snap is None:
        raise ExecutionApprovalError(
            "SNAPSHOT_NOT_FOUND",
            f"Execution approval snapshot {snapshot_id} was not found.",
            status_code=404,
        )
    return snap


def _recompute_from_snapshot(snap: dict[str, Any], *, final_prompt_text: str) -> dict[str, Any]:
    """Recompute identity for an edited prompt, holding every OTHER envelope field
    fixed to the snapshot's frozen values."""
    env = json.loads(snap.get("execution_envelope_json") or "{}")
    return compute_dispatch_identity(
        mode=env.get("mode") or snap.get("logical_mode") or "",
        final_prompt_text=final_prompt_text,
        source_mode=env.get("source_mode"),
        model=env.get("model"),
        aspect=env.get("aspect"),
        duration_s=env.get("duration_s"),
        count=env.get("count"),
        image_model=env.get("image_model"),
        asset_media_ids=env.get("asset_fingerprints"),
    )
