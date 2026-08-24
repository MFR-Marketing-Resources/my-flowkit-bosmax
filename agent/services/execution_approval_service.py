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
import logging
import os
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from agent.db import execution_approval_crud as _crud
from agent.services.production_prompt_approval_service import scan_prompt_text
from agent.services import video_execution_profile_service as _profile_service

logger = logging.getLogger(__name__)


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

# Corrective (2026-08-19): approval is REQUIRED for ALL active generation modes,
# IMG included. Credit-free (owner law: no cost gating/warnings for image) does NOT
# mean approval-optional. The dispatch hard-block below fires for every enforced
# mode. Only the FlowClient CREDIT backstop stays video-only (captchaAction
# VIDEO_GENERATION), since credit spend is a video-only concern.


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


PROVIDER_TARGET_ACK_VERSION = "FLOW_PROVIDER_TARGET_ACK_V1"


def build_provider_target_authorization(
    *,
    lane: str,
    route: str,
    model: str,
    duration_s: int,
    aspect_ratio: str,
    product_id: str,
    copy_id: str,
    profile_digest: str,
    sweetwps_digest: str,
    compositor_digest: str,
    compiler_digest: str,
    owner_credit_ceiling: int | float,
) -> dict[str, Any]:
    """Build the immutable target used by the Flow permission handshake.

    The provider may only be approved after its post-steer response proves the
    model and duration. All other fields are already bound by the current
    product/copy/profile/snapshot authority. Folding them into one digest keeps
    that proof from being reused for a different lane, route, product, or budget.
    """
    try:
        duration = int(duration_s)
    except (TypeError, ValueError) as exc:
        raise ExecutionApprovalError(
            "PROVIDER_TARGET_DURATION_INVALID",
            "The provider target duration must be an integer number of seconds.",
        ) from exc
    if duration <= 0:
        raise ExecutionApprovalError(
            "PROVIDER_TARGET_DURATION_INVALID",
            "The provider target duration must be positive.",
        )
    try:
        ceiling = float(owner_credit_ceiling)
    except (TypeError, ValueError) as exc:
        raise ExecutionApprovalError(
            "PROVIDER_TARGET_CREDIT_CEILING_INVALID",
            "The owner credit ceiling must be numeric.",
        ) from exc
    if ceiling <= 0:
        raise ExecutionApprovalError(
            "PROVIDER_TARGET_CREDIT_CEILING_INVALID",
            "The owner credit ceiling must be positive.",
        )
    if ceiling.is_integer():
        ceiling = int(ceiling)
    target = {
        "lane": _norm(lane).upper().replace("-", "_"),
        "route": _norm(route).upper(),
        "model": _norm(model).lower(),
        "duration_s": duration,
        "aspect_ratio": _norm(aspect_ratio),
        "product_id": _norm(product_id),
        "copy_id": _norm(copy_id),
        "profile_digest": _norm(profile_digest),
        "sweetwps_digest": _norm(sweetwps_digest),
        "compositor_digest": _norm(compositor_digest),
        "compiler_digest": _norm(compiler_digest),
        "owner_credit_ceiling": ceiling,
    }
    missing = [key for key, value in target.items() if value in (None, "")]
    if missing:
        raise ExecutionApprovalError(
            "PROVIDER_TARGET_AUTHORIZATION_INCOMPLETE",
            "Every canonical provider target field is required.",
            details={"missing": missing},
        )
    return {
        "version": PROVIDER_TARGET_ACK_VERSION,
        "target": target,
        "target_digest": _sha256_text(_stable_json(target)),
    }


def build_provider_target_acknowledgement(
    target_authorization: Mapping[str, Any],
    *,
    provider_text: str,
    model_duration_acknowledged: bool,
) -> dict[str, Any]:
    """Create a safe, provider-text-backed target acknowledgement receipt."""
    if not isinstance(target_authorization, Mapping):
        raise ExecutionApprovalError(
            "PROVIDER_TARGET_AUTHORIZATION_REQUIRED",
            "The canonical target authorization is required before approval.",
        )
    target = target_authorization.get("target")
    target_digest = _norm(target_authorization.get("target_digest"))
    if not isinstance(target, Mapping) or not target_digest:
        raise ExecutionApprovalError(
            "PROVIDER_TARGET_AUTHORIZATION_INVALID",
            "The canonical target authorization is malformed.",
        )
    proposed_digest = _sha256_text(_stable_json(dict(target)))
    if proposed_digest != target_digest:
        raise ExecutionApprovalError(
            "PROVIDER_TARGET_DIGEST_MISMATCH",
            "The proposed target does not equal the canonical authorized target.",
            details={
                "canonical_target_digest": target_digest,
                "proposed_target_digest": proposed_digest,
            },
        )
    if not model_duration_acknowledged:
        raise ExecutionApprovalError(
            "PRE_APPROVAL_SETTINGS_ACK_REQUIRED",
            "The provider did not acknowledge the canonical model and duration.",
            details={"target_digest": target_digest},
        )
    return {
        "version": PROVIDER_TARGET_ACK_VERSION,
        "target_digest": target_digest,
        "proposed_target_digest": proposed_digest,
        "provider_text_sha256": _sha256_text(str(provider_text or "")),
        "model_duration_acknowledged": True,
        "source": "FLOW_PERMISSION_PROPOSAL_AFTER_TARGET_STEER",
    }


async def record_provider_target_acknowledgement(
    snapshot_id: str,
    *,
    target_authorization: Mapping[str, Any],
    acknowledgement: Mapping[str, Any],
) -> dict[str, Any]:
    """Persist one exact target acknowledgement on the official snapshot."""
    if not isinstance(target_authorization, Mapping) or not isinstance(acknowledgement, Mapping):
        raise ExecutionApprovalError(
            "PROVIDER_TARGET_ACK_INVALID",
            "The canonical target and acknowledgement receipt are required.",
        )
    snap = await _require(snapshot_id)
    if snap.get("approval_state") not in {
        ApprovalState.APPROVED,
        ApprovalState.DISPATCHED,
    }:
        raise ExecutionApprovalError(
            "PROVIDER_TARGET_ACK_SNAPSHOT_NOT_ACTIVE",
            "Target acknowledgement requires the current approved snapshot.",
            details={"snapshot_id": snapshot_id, "approval_state": snap.get("approval_state")},
        )
    canonical_digest = _norm(target_authorization.get("target_digest"))
    acknowledged_digest = _norm(acknowledgement.get("target_digest"))
    proposed_digest = _norm(acknowledgement.get("proposed_target_digest"))
    if not canonical_digest or canonical_digest != acknowledged_digest or canonical_digest != proposed_digest:
        raise ExecutionApprovalError(
            "PROVIDER_TARGET_DIGEST_MISMATCH",
            "The provider acknowledgement does not match the canonical target.",
            details={
                "canonical_target_digest": canonical_digest,
                "acknowledged_target_digest": acknowledged_digest,
                "proposed_target_digest": proposed_digest,
            },
        )
    if snap.get("provider_target_digest") and snap.get("provider_target_digest") != canonical_digest:
        raise ExecutionApprovalError(
            "STALE_PROVIDER_TARGET_ACKNOWLEDGEMENT",
            "A different target acknowledgement is already bound to this snapshot.",
            details={"snapshot_id": snapshot_id},
        )
    now = _now()
    safe_ack = dict(acknowledgement)
    return await _crud.update_snapshot(
        snapshot_id,
        provider_target_digest=canonical_digest,
        provider_target_ack_json=_stable_json(safe_ack),
        provider_target_acknowledged_at=now,
        provider_target_ack_source=_norm(safe_ack.get("source")) or "FLOW_PERMISSION_PROPOSAL",
        updated_at=now,
    )


def _provider_profile_binding(
    provider_profile: Mapping[str, Any] | None,
    provider_profile_digest: str | None,
) -> tuple[str | None, str | None]:
    """Return the shared provider digest/id without folding lane data into it.

    The provider digest is stored as one provider-affecting component of the
    execution envelope.  It is intentionally distinct from the envelope hash:
    changing a lane adapter still changes the envelope, while the same provider
    certification can be reused by another lane with a different envelope.
    """
    digest = _norm(provider_profile_digest) or None
    profile_id = None
    if isinstance(provider_profile, Mapping):
        digest = digest or _norm(
            provider_profile.get("provider_profile_digest")
            or provider_profile.get("profile_digest")
        ) or None
        profile_id = _norm(provider_profile.get("profile_id")) or None
        if not digest:
            from agent.services.provider_execution_profile import (
                resolve_provider_execution_profile,
            )

            resolved = resolve_provider_execution_profile(provider_profile)
            digest = resolved["provider_profile_digest"]
            profile_id = profile_id or resolved["profile_id"]
    return digest, profile_id


def _infer_provider_profile_for_dispatch(
    *,
    mode: str | None,
    source_mode: str | None,
    model: str | None,
    aspect: str | None,
    duration_s: int | None,
    count: int | None,
    product_id: str | None,
    asset_fingerprints: list[str] | None,
    asset_media_ids: list[str] | None,
) -> dict[str, Any] | None:
    """Infer only an already-captured profile from the normal dispatch tuple.

    This keeps API review and backend dispatch parity when a caller does not
    explicitly echo ``provider_profile``.  It is intentionally narrow: an
    unproven tuple returns ``None`` rather than being promoted into a profile.
    """
    if str(mode or "").strip().upper() != "F2V":
        return None
    if str(source_mode or "").strip().upper() != "HYBRID":
        return None
    if str(aspect or "").strip() != "9:16":
        return None
    if int(count or 1) != 1 or int(duration_s or 0) != 10:
        return None
    if not (product_id or asset_fingerprints or asset_media_ids):
        return None
    try:
        from agent.services import video_models
        from agent.services.provider_execution_profile import (
            resolve_provider_execution_profile,
        )

        if video_models.resolve(model).get("key") != "omni_flash":
            return None
        return resolve_provider_execution_profile(
            provider="GOOGLE_FLOW",
            model="omni_flash",
            duration_seconds=10,
            prompt_block_count=1,
            aspect_ratio="9:16",
            output_count=1,
            reference_topology="ONE_REFERENCE",
            generation_type="reference_frame_2_video",
            execution_transport="flow_creation_agent",
            provider_model_key="abra_r2v_10s",
            capability_contract_version="flow-agent-reference-omni10-v1",
            provider_tool="generate_video_with_references",
            provider_rpc="agent_stream_chat",
        )
    except (TypeError, ValueError):
        return None


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
    asset_fingerprints: list[str] | None = None,
    asset_media_ids: list[str] | None = None,
    product_id: str | None = None,
    execution_identity: dict[str, Any] | None = None,
    execution_profile_context: Mapping[str, Any] | None = None,
    provider_profile: Mapping[str, Any] | None = None,
    provider_profile_digest: str | None = None,
) -> dict[str, Any]:
    """THE canonical envelope+hash builder (Envelope v2). Called with identical
    semantics at review time and at the dispatch boundary, so equal provider-affecting
    inputs always yield equal hashes.

    Returns ``{prompt_sha256, execution_envelope, execution_envelope_sha256}``.
    The envelope keys are a fixed shape; unused fields normalise to ``None`` and
    still participate in the hash, so adding/removing a provider-affecting field
    later is an explicit, versioned change — never silent.

    ``product_id`` anchors the product identity STABLY. For product-aware IMG the
    caller binds on ``product_id`` and passes NO ``asset_media_ids`` — the product
    visual is derived deterministically from the product authority + the grounded
    prompt, so the volatile per-session Flow media id must not enter the approval
    hash (it would make review != dispatch for the same approved product).
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

    raw_fps = asset_fingerprints if asset_fingerprints is not None else (asset_media_ids or [])
    fps = sorted({_norm(m) for m in raw_fps if _norm(m)})

    envelope = {
        "envelope_version": 2,
        "mode": _norm(mode).upper(),
        "prompt_sha256": prompt_sha256,
        "source_mode": (_norm(source_mode).upper() or None),
        "model": (_norm(model) or None),
        "aspect": (_norm(aspect) or None),
        "duration_s": _int_or_none(duration_s),
        "count": _int_or_none(count),
        "image_model": (_norm(image_model) or None),
        # Stable product anchor (never the volatile Flow media id for product IMG).
        "product_id": (_norm(product_id) or None),
        # Server-authoritative CANONICAL fingerprints (PR #815): product-visual SHA
        # for product-backed HYBRID/F2V, explicit locking for manual FRAMES; falls
        # back to asset_media_ids. Sorted + de-duped so ordering never changes the
        # hash. A self-heal re-upload that changes the CANONICAL identity IS an asset
        # change (contract: "asset changed -> INVALIDATED -> REVIEW_REQUIRED").
        "asset_fingerprints": fps,
    }
    if execution_identity is not None:
        # Faceless V1 carries a structured, persisted receipt. Canonicalize it
        # before hashing so key order cannot create a false approval mismatch.
        envelope["execution_identity"] = json.loads(_stable_json(execution_identity))
    if execution_profile_context is not None:
        # The profile and all current authority digests are part of the frozen
        # envelope. A changed duration, route, lane adapter, Product Truth,
        # Copy V2, SweetWPS, compositor, or compiler digest therefore cannot
        # reuse an older APPROVED snapshot.
        try:
            envelope["execution_profile_context"] = json.loads(
                _stable_json(
                    _profile_service.normalize_approval_context(
                        execution_profile_context
                    )
                )
            )
        except _profile_service.ExecutionProfileError as exc:
            raise ExecutionApprovalError(
                "EXECUTION_PROFILE_CONTEXT_INVALID",
                str(exc),
                details={"code": exc.code, "details": exc.details},
            ) from exc
    bound_provider_digest, bound_provider_id = _provider_profile_binding(
        provider_profile, provider_profile_digest,
    )
    if bound_provider_digest:
        # This is a separate digest from execution_envelope_sha256.  It makes
        # the shared certification reference explicit without making a surface
        # lane part of provider certification identity.
        envelope["provider_profile_digest"] = bound_provider_digest
    return {
        "prompt_sha256": prompt_sha256,
        "execution_envelope": envelope,
        "execution_envelope_sha256": hashlib.sha256(
            _stable_json(envelope).encode("utf-8")
        ).hexdigest(),
        "provider_profile_digest": bound_provider_digest,
        "provider_profile_id": bound_provider_id,
    }


async def resolve_canonical_asset_fingerprints(
    *,
    mode: str,
    source_mode: str | None = None,
    product_id: str | None = None,
    asset_fingerprints: list[str] | None = None,
    asset_media_ids: list[str] | None = None,
) -> list[str]:
    """Server-authoritative canonical asset fingerprint resolver.

    For product-backed HYBRID / F2V / IMG with product_id (corrective GAP 3 extends
    the authority to IMG):
      Derive the canonical product visual fingerprint from the Product Visual
      authority: PRODUCT_VISUAL|<product_id>|<slot_key>|<full_sha256>.
      This binds the exact byte content of the official product visual. Provider
      transport media UUIDs (newly uploaded during generation) do NOT participate
      in the logical approval hash. If a product has no resolvable canonical visual
      the resolver degrades to the explicit/empty asset set — identically at review
      and dispatch, so parity holds either way.

      FAIL-CLOSED: If canonical fingerprint resolution fails for a product-backed
      HYBRID/F2V execution, this function MUST raise ExecutionApprovalError. It
      must NEVER silently fall back to caller-supplied asset IDs or fingerprints.

    For manual frame lanes (source_mode == FRAMES) and explicit assets:
      Retain strict locking to the explicit frame/asset fingerprints/IDs
      (manual-frame locking is never weakened).
    """
    norm_source = _norm(source_mode).upper()
    norm_mode = _norm(mode).upper()

    product_backed = product_id and norm_source != "FRAMES" and (
        norm_source == "HYBRID" or norm_mode in ("F2V", "IMG")
    )
    if product_backed:
        from agent.services.product_visual_grounding_resolver import (
            get_canonical_product_visual_fingerprint,
        )
        try:
            pv_fp = await get_canonical_product_visual_fingerprint(product_id, slot_key="start_frame")
            if not pv_fp:
                raise ExecutionApprovalError(
                    "PRODUCT_VISUAL_REFERENCE_REQUIRED",
                    f"PRODUCT_VISUAL_REFERENCE_REQUIRED: Canonical product visual fingerprint for product '{product_id}' resolved empty.",
                    details={"product_id": product_id},
                )
            return [pv_fp]
        except ExecutionApprovalError:
            raise
        except Exception as exc:
            logger.error(
                "Failed to resolve canonical product visual fingerprint for product %s: %s",
                product_id,
                exc,
            )
            raise ExecutionApprovalError(
                "PRODUCT_VISUAL_REFERENCE_REQUIRED",
                f"PRODUCT_VISUAL_REFERENCE_REQUIRED: Failed to resolve canonical product visual fingerprint for product '{product_id}': {exc}",
                details={"product_id": product_id, "error": str(exc)},
            ) from exc

    if asset_fingerprints is not None:
        return sorted({_norm(f) for f in asset_fingerprints if _norm(f)})

    return sorted({_norm(m) for m in (asset_media_ids or []) if _norm(m)})


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
    asset_fingerprints: list[str] | None = None,
    asset_media_ids: list[str] | None = None,
    execution_identity: dict[str, Any] | None = None,
    execution_profile_context: Mapping[str, Any] | None = None,
    provider_profile: Mapping[str, Any] | None = None,
    review_session_id: str | None = None,
    created_by: str | None = None,
    manifest_id: str | None = None,
    manifest_item_key: str | None = None,
) -> dict[str, Any]:
    """Freeze a FINAL provider-ready envelope for human review (REVIEW_REQUIRED).

    ``final_prompt_text`` MUST already be the fully grounded, provider-ready
    prompt (product-truth / grounding / safety / asset-resolution applied
    BEFORE review — never after approval)."""
    canonical_fps = await resolve_canonical_asset_fingerprints(
        mode=logical_mode,
        source_mode=source_mode,
        product_id=product_id,
        asset_fingerprints=asset_fingerprints,
        asset_media_ids=asset_media_ids,
    )
    provider_profile = provider_profile or _infer_provider_profile_for_dispatch(
        mode=logical_mode,
        source_mode=source_mode,
        model=model,
        aspect=aspect,
        duration_s=duration_s,
        count=count,
        product_id=product_id,
        asset_fingerprints=canonical_fps,
        asset_media_ids=asset_media_ids,
    )
    identity = compute_dispatch_identity(
        mode=logical_mode,
        final_prompt_text=final_prompt_text,
        source_mode=source_mode,
        model=model,
        aspect=aspect,
        duration_s=duration_s,
        count=count,
        image_model=image_model,
        asset_fingerprints=canonical_fps,
        product_id=product_id,
        execution_identity=execution_identity,
        execution_profile_context=execution_profile_context,
        provider_profile=provider_profile,
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
        "manifest_id": (_norm(manifest_id) or None),
        "manifest_item_key": (_norm(manifest_item_key) or None),
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
        provider_target_digest=None,
        provider_target_ack_json=None,
        provider_target_acknowledged_at=None,
        provider_target_ack_source=None,
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


async def reconcile_pre_provider_failure(
    snapshot_id: str,
    *,
    reason: str,
) -> dict[str, Any]:
    """Invalidate an approval after an audited provider-free failure.

    A snapshot can be ``DISPATCHED`` when the dispatch-boundary equality check
    ran, but still have no provider binding.  That narrow state is recoverable:
    it is invalidated without erasing the dispatched envelope/timestamp, while
    any snapshot carrying a provider job binding remains immutable.
    """

    snap = await _require(snapshot_id)
    state = snap.get("approval_state")
    if state == ApprovalState.INVALIDATED:
        return snap
    if state == ApprovalState.DISPATCHED and _norm(snap.get("provider_job_id")):
        raise ExecutionApprovalError(
            "PRE_PROVIDER_SNAPSHOT_HAS_PROVIDER_BINDING",
            "A dispatched snapshot with a provider binding cannot be reconciled as pre-provider.",
            details={"snapshot_id": snapshot_id, "provider_job_id": snap.get("provider_job_id")},
        )
    if state not in {
        ApprovalState.REVIEW_REQUIRED,
        ApprovalState.EDITED,
        ApprovalState.APPROVED,
        ApprovalState.DISPATCHED,
    }:
        raise ExecutionApprovalError(
            "PRE_PROVIDER_SNAPSHOT_STATE_UNSUPPORTED",
            f"Snapshot in state {state} cannot be reconciled.",
            details={"snapshot_id": snapshot_id, "approval_state": state},
        )
    now = _now()
    return await _crud.update_snapshot(
        snapshot_id,
        approval_state=ApprovalState.INVALIDATED,
        approved_prompt_sha256=None,
        approved_execution_envelope_sha256=None,
        invalidation_reason=_norm(reason) or "PRE_PROVIDER_FAILURE",
        updated_at=now,
    )


async def resolve_manifest_approved_snapshot(
    *,
    manifest_id: str,
    mode: str,
    final_prompt_text: str,
    source_mode: str | None = None,
    model: str | None = None,
    aspect: str | None = None,
    duration_s: int | None = None,
    count: int | None = None,
    image_model: str | None = None,
    asset_fingerprints: list[str] | None = None,
    asset_media_ids: list[str] | None = None,
    product_id: str | None = None,
    execution_identity: dict[str, Any] | None = None,
    execution_profile_context: Mapping[str, Any] | None = None,
    provider_profile: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """RESOLVE / BIND (never manufacture) a human-approved manifest item whose
    frozen execution-envelope SHA (canonical Envelope v2 identity — PR #815 server-
    authoritative fingerprints) EXACTLY matches this dispatch. This is the ONLY way
    a non-UI dispatch (queue / bulk / scheduler / Montage / Extend) inherits
    approval — by referencing an already human-approved manifest whose item hash
    matches. It NEVER creates or approves anything from the live dispatch envelope;
    no approved manifest item match -> returns None and the dispatch stays
    fail-closed. (No provenance string manufactures human approval.)"""
    if not _norm(manifest_id):
        return None
    canonical_fps = await resolve_canonical_asset_fingerprints(
        mode=mode,
        source_mode=source_mode,
        product_id=product_id,
        asset_fingerprints=asset_fingerprints,
        asset_media_ids=asset_media_ids,
    )
    provider_profile = provider_profile or _infer_provider_profile_for_dispatch(
        mode=mode,
        source_mode=source_mode,
        model=model,
        aspect=aspect,
        duration_s=duration_s,
        count=count,
        product_id=product_id,
        asset_fingerprints=canonical_fps,
        asset_media_ids=asset_media_ids,
    )
    identity = compute_dispatch_identity(
        mode=mode,
        final_prompt_text=final_prompt_text,
        source_mode=source_mode,
        model=model,
        aspect=aspect,
        duration_s=duration_s,
        count=count,
        image_model=image_model,
        asset_fingerprints=canonical_fps,
        product_id=product_id,
        execution_identity=execution_identity,
        execution_profile_context=execution_profile_context,
        provider_profile=provider_profile,
    )
    return await _crud.find_approved_manifest_item(
        _norm(manifest_id), identity["execution_envelope_sha256"],
    )


async def ensure_upstream_approved_snapshot(
    *,
    mode: str,
    final_prompt_text: str,
    surface: str = "upstream",
    provenance: str = "upstream-approval",
    product_id: str | None = None,
    source_mode: str | None = None,
    model: str | None = None,
    aspect: str | None = None,
    duration_s: int | None = None,
    count: int | None = None,
    image_model: str | None = None,
    asset_fingerprints: list[str] | None = None,
    asset_media_ids: list[str] | None = None,
    execution_profile_context: Mapping[str, Any] | None = None,
    provider_profile: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """RESOLVE / BIND-ONLY upstream approval (corrective GAP 2 refactor of the
    former create-and-auto-approve helper). Computes the canonical Envelope v2
    identity (PR #815 server-authoritative fingerprints) and returns an EXISTING
    APPROVED snapshot whose frozen envelope SHA matches — or None. It MUST NOT
    create or approve a snapshot from provenance, so a path with no genuine upstream
    human approval stays fail-closed. Prefer resolve_manifest_approved_snapshot
    (manifest-scoped) for the multi-op dispatch surfaces."""
    canonical_fps = await resolve_canonical_asset_fingerprints(
        mode=mode,
        source_mode=source_mode,
        product_id=product_id,
        asset_fingerprints=asset_fingerprints,
        asset_media_ids=asset_media_ids,
    )
    provider_profile = provider_profile or _infer_provider_profile_for_dispatch(
        mode=mode,
        source_mode=source_mode,
        model=model,
        aspect=aspect,
        duration_s=duration_s,
        count=count,
        product_id=product_id,
        asset_fingerprints=canonical_fps,
        asset_media_ids=asset_media_ids,
    )
    identity = compute_dispatch_identity(
        mode=mode,
        final_prompt_text=final_prompt_text,
        source_mode=source_mode,
        model=model,
        aspect=aspect,
        duration_s=duration_s,
        count=count,
        image_model=image_model,
        asset_fingerprints=canonical_fps,
        product_id=product_id,
        execution_profile_context=execution_profile_context,
        provider_profile=provider_profile,
    )
    return await _crud.find_approved_by_envelope(identity["execution_envelope_sha256"])


# --------------------------------------------------------------------------- #
# Approved Generation Manifest lifecycle (explicit multi-operation approval)
# --------------------------------------------------------------------------- #

async def create_manifest(
    *,
    surface: str,
    items: list[dict[str, Any]],
    product_id: str | None = None,
    logical_mode: str | None = None,
    run_ref: str | None = None,
    created_by: str | None = None,
) -> dict[str, Any]:
    """Create an Approved Generation Manifest — one review snapshot per provider
    operation. Each item freezes the exact provider-ready envelope of that op. The
    operator reviews/edits, then approves the WHOLE manifest atomically."""
    manifest_id = "eam_" + uuid.uuid4().hex[:16]
    now = _now()
    review_session_id = "rev_" + uuid.uuid4().hex[:12]
    await _crud.create_manifest({
        "manifest_id": manifest_id,
        "surface": _norm(surface),
        "product_id": product_id,
        "logical_mode": (_norm(logical_mode).upper() or None),
        "run_ref": (_norm(run_ref) or None),
        "state": "REVIEW_REQUIRED",
        "item_count": len(items),
        "approved_version": 0,
        "approved_by": None,
        "approved_at": None,
        "invalidation_reason": None,
        "created_by": (_norm(created_by) or None),
        "created_at": now,
        "updated_at": now,
    })
    for idx, item in enumerate(items):
        item_key = _norm(item.get("item_key")) or f"item_{idx:04d}"
        await create_review_snapshot(
            surface=surface,
            logical_mode=item.get("mode") or logical_mode or "",
            final_prompt_text=item.get("final_prompt_text") or "",
            product_id=item.get("product_id", product_id),
            source_mode=item.get("source_mode"),
            model=item.get("model"),
            aspect=item.get("aspect"),
            duration_s=item.get("duration_s"),
            count=item.get("count"),
            image_model=item.get("image_model"),
            asset_media_ids=item.get("asset_media_ids"),
            execution_identity=item.get("execution_identity"),
            execution_profile_context=item.get("execution_profile_context"),
            provider_profile=item.get("provider_profile"),
            review_session_id=review_session_id,
            created_by=created_by,
            manifest_id=manifest_id,
            manifest_item_key=item_key,
        )
    return await get_manifest_with_items(manifest_id)


async def get_manifest_with_items(manifest_id: str) -> dict[str, Any]:
    manifest = await _crud.get_manifest(manifest_id)
    if manifest is None:
        raise ExecutionApprovalError(
            "MANIFEST_NOT_FOUND",
            f"Approval manifest {manifest_id} was not found.",
            status_code=404,
        )
    manifest["items"] = await _crud.list_manifest_items(manifest_id)
    return manifest


async def edit_manifest_item(
    manifest_id: str,
    snapshot_id: str,
    *,
    edited_prompt_text: str,
    editor_id: str | None = None,
) -> dict[str, Any]:
    manifest = await _crud.get_manifest(manifest_id)
    if manifest is None:
        raise ExecutionApprovalError("MANIFEST_NOT_FOUND", "manifest not found", status_code=404)
    if manifest["state"] == "APPROVED":
        raise ExecutionApprovalError(
            "MANIFEST_IMMUTABLE",
            "An APPROVED manifest is immutable; invalidate it to revise.",
        )
    snap = await _crud.get_snapshot(snapshot_id)
    if snap is None or snap.get("manifest_id") != manifest_id:
        raise ExecutionApprovalError(
            "SNAPSHOT_NOT_IN_MANIFEST", "item not in manifest", status_code=404,
        )
    await apply_edit(snapshot_id, edited_prompt_text=edited_prompt_text, editor_id=editor_id)
    await _crud.update_manifest(manifest_id, updated_at=_now())
    return await get_manifest_with_items(manifest_id)


async def approve_manifest(manifest_id: str, *, approved_by: str) -> dict[str, Any]:
    """Approve the WHOLE manifest atomically. Every item must be scan-clean; a
    single dirty item refuses the approval. On success each item snapshot becomes
    APPROVED and the manifest is immutable — the exact human-approved authority
    that dispatches resolve against."""
    manifest = await _crud.get_manifest(manifest_id)
    if manifest is None:
        raise ExecutionApprovalError("MANIFEST_NOT_FOUND", "manifest not found", status_code=404)
    if manifest["state"] == "APPROVED":
        return await get_manifest_with_items(manifest_id)
    items = await _crud.list_manifest_items(manifest_id)
    if not items:
        raise ExecutionApprovalError("MANIFEST_EMPTY", "manifest has no items")
    dirty = [i["snapshot_id"] for i in items if not int(i.get("scan_clean") or 0)]
    if dirty:
        raise ExecutionApprovalError(
            "MANIFEST_SCAN_NOT_CLEAN",
            "One or more manifest items failed the safety scan; approval refused.",
            details={"dirty_items": dirty},
        )
    for item in items:
        await approve_snapshot(item["snapshot_id"], approved_by=approved_by)
    now = _now()
    await _crud.update_manifest(
        manifest_id,
        state="APPROVED",
        approved_version=int(manifest.get("approved_version") or 0) + 1,
        approved_by=_norm(approved_by) or "operator",
        approved_at=now,
        invalidation_reason=None,
        updated_at=now,
    )
    return await get_manifest_with_items(manifest_id)


async def invalidate_manifest(manifest_id: str, *, reason: str) -> dict[str, Any]:
    manifest = await _crud.get_manifest(manifest_id)
    if manifest is None:
        raise ExecutionApprovalError("MANIFEST_NOT_FOUND", "manifest not found", status_code=404)
    for item in await _crud.list_manifest_items(manifest_id):
        if item.get("approval_state") in _INVALIDATABLE_FROM:
            await invalidate_snapshot(item["snapshot_id"], reason=reason)
    await _crud.update_manifest(
        manifest_id,
        state="INVALIDATED",
        invalidation_reason=_norm(reason) or "INVALIDATED",
        updated_at=_now(),
    )
    return await get_manifest_with_items(manifest_id)


async def approved_manifest_id_for_run(
    run_ref: str,
    *,
    surface: str | None = None,
) -> str | None:
    """Dispatch-side lookup: the APPROVED manifest_id for a multi-op run (Montage /
    bulk / queue / Production Studio). A non-UI dispatch calls this with its run id
    and threads the result into ``start_generate(manifest_id=...)``. Returns None
    when no approved manifest exists yet — the dispatch then fails closed under
    enforcement (nothing is auto-approved)."""
    if not _norm(run_ref):
        return None
    manifest = await _crud.find_latest_approved_manifest_by_run_ref(
        _norm(run_ref), surface=surface,
    )
    return manifest["manifest_id"] if manifest else None


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
    asset_fingerprints: list[str] | None = None,
    asset_media_ids: list[str] | None = None,
    product_id: str | None = None,
    snapshot_id: str | None = None,
    provider_job_id: str | None = None,
    execution_identity: dict[str, Any] | None = None,
    execution_profile_context: Mapping[str, Any] | None = None,
    provider_profile: Mapping[str, Any] | None = None,
    provider_profile_digest: str | None = None,
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
    canonical_fps = await resolve_canonical_asset_fingerprints(
        mode=mode,
        source_mode=source_mode,
        product_id=product_id,
        asset_fingerprints=asset_fingerprints,
        asset_media_ids=asset_media_ids,
    )
    provider_profile = provider_profile or _infer_provider_profile_for_dispatch(
        mode=mode,
        source_mode=source_mode,
        model=model,
        aspect=aspect,
        duration_s=duration_s,
        count=count,
        product_id=product_id,
        asset_fingerprints=canonical_fps,
        asset_media_ids=asset_media_ids,
    )
    identity = compute_dispatch_identity(
        mode=mode,
        final_prompt_text=final_prompt_text,
        source_mode=source_mode,
        model=model,
        aspect=aspect,
        duration_s=duration_s,
        count=count,
        image_model=image_model,
        asset_fingerprints=canonical_fps,
        product_id=product_id,
        execution_identity=execution_identity,
        execution_profile_context=execution_profile_context,
        provider_profile=provider_profile,
        provider_profile_digest=provider_profile_digest,
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
        # An edit changes only the prompt — hold the FROZEN canonical fingerprints
        # fixed (never re-resolve assets on an edit).
        asset_fingerprints=env.get("asset_fingerprints"),
        product_id=env.get("product_id") or snap.get("product_id"),
        execution_identity=env.get("execution_identity"),
        execution_profile_context=env.get("execution_profile_context"),
        provider_profile_digest=env.get("provider_profile_digest"),
    )

