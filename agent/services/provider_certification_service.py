"""Shared, artifact-backed provider certification for active video routes.

Certification is keyed by the immutable duration/model execution profile.  A
representative lane is evidence provenance only; it is never part of the
provider-proof identity.  The service deliberately does not edit ``models.json``
or any direct-lane flags and never promotes a reservation without a real
provider artifact, measured credit delta, and an authenticated frame-QC receipt.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from agent.db import provider_certification_crud as _crud
from agent.services import video_execution_profile_service as _profiles


CERTIFICATION_RESERVED = "RESERVED"
CERTIFICATION_SUBMITTED = "SUBMITTED"
CERTIFICATION_ARTIFACT_PENDING = "ARTIFACT_PENDING"
CERTIFICATION_CERTIFIED = "CERTIFIED"
CERTIFICATION_FAILED = "FAILED"

_REOPENABLE_PRE_PROVIDER_FAILURES = {
    "FLOW_EDITOR_BINDING_REQUIRED",
    "PROFILE_CERTIFICATION_PRE_PROVIDER_FAILED",
}

# Owner-authorized retirement of a submitted-but-unsuitable capture (e.g. a
# wrong-aspect artifact) reopens the exact profile for ONE corrected capture.
CERTIFICATION_ARTIFACT_UNSUITABLE = "PROFILE_CERTIFICATION_ARTIFACT_UNSUITABLE"

# Failure codes ``reserve_capture`` may archive+recreate on the next capture.
# The pre-provider set is preserved verbatim; the supersede code is unioned in
# without altering existing pre-provider reopen behavior.
_REOPENABLE_FAILURES = _REOPENABLE_PRE_PROVIDER_FAILURES | {
    CERTIFICATION_ARTIFACT_UNSUITABLE,
}


class ProviderCertificationError(ValueError):
    """Structured fail-closed certification error."""

    def __init__(self, code: str, message: str = "", *, details: Any = None):
        self.code = code
        self.details = details or {}
        super().__init__(message or code)


def validate_capture_contract(
    *,
    profile_context: Mapping[str, Any] | None,
    mode: str,
    source_mode: str | None,
    model: str | None,
    duration_s: int | None,
    aspect: str | None,
    num_videos: int,
    image_media_ids: list[str] | None,
    product_id: str | None,
    production_recipe: str | None,
    surface_lane: str | None,
    product_visual_custody: Mapping[str, Any] | None,
    confirm_live_credit_burn: bool,
    maximum_provider_operations: int | None,
    max_retry_operations: int,
    auth_context: Any,
) -> dict[str, Any]:
    """Validate the one bounded representative capture contract.

    This is intentionally narrower than normal generation: it cannot be used
    to certify a direct lane, another duration, another model, another lane,
    or a reference-bearing request.
    """

    roles = {str(role).upper() for role in getattr(auth_context, "role_codes", ())}
    permissions = {
        str(permission) for permission in getattr(auth_context, "permission_codes", ())
    }
    if auth_context is None or "OWNER" not in roles or "production.execute" not in permissions:
        raise ProviderCertificationError(
            "PROFILE_CERTIFICATION_OWNER_REQUIRED",
            "Only an authenticated OWNER with production.execute may start capture.",
        )
    if str(mode or "").upper() != "T2V":
        raise ProviderCertificationError("PROFILE_CERTIFICATION_MODE_MUST_BE_T2V")
    if str(source_mode or "").upper() != "T2V":
        raise ProviderCertificationError("PROFILE_CERTIFICATION_SOURCE_MODE_MUST_BE_T2V")
    if str(surface_lane or "").upper() != "FACELESS":
        raise ProviderCertificationError("PROFILE_CERTIFICATION_SURFACE_MUST_BE_FACELESS")
    if str(production_recipe or "").upper() != "FACELESS":
        raise ProviderCertificationError("PROFILE_CERTIFICATION_RECIPE_MUST_BE_FACELESS")
    if str(model or "").strip() != "veo_3_1_lite":
        raise ProviderCertificationError("PROFILE_CERTIFICATION_MODEL_MUST_BE_VEO_3_1_LITE")
    if int(duration_s or 0) != 8:
        raise ProviderCertificationError("PROFILE_CERTIFICATION_DURATION_MUST_BE_8")
    if str(aspect or "").strip() != "9:16":
        raise ProviderCertificationError("PROFILE_CERTIFICATION_ASPECT_MUST_BE_9_16")
    if int(num_videos or 0) != 1:
        raise ProviderCertificationError("PROFILE_CERTIFICATION_COUNT_MUST_BE_1")
    if any(_norm(value) for value in (image_media_ids or [])):
        raise ProviderCertificationError("PROFILE_CERTIFICATION_REFERENCES_FORBIDDEN")
    if not _norm(product_id):
        raise ProviderCertificationError("PROFILE_CERTIFICATION_PRODUCT_REQUIRED")
    if confirm_live_credit_burn is not True:
        raise ProviderCertificationError("PROFILE_CERTIFICATION_CONFIRMATION_REQUIRED")
    if int(maximum_provider_operations or 0) != 1:
        raise ProviderCertificationError("PROFILE_CERTIFICATION_OPERATION_BUDGET_MUST_BE_1")
    if int(max_retry_operations or 0) != 0:
        raise ProviderCertificationError("PROFILE_CERTIFICATION_RETRIES_MUST_BE_0")
    if not isinstance(product_visual_custody, Mapping):
        raise ProviderCertificationError("PROFILE_CERTIFICATION_CUSTODY_REQUIRED")
    if product_visual_custody.get("provider_route") != "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE":
        raise ProviderCertificationError("PROFILE_CERTIFICATION_ACTIVE_ROUTE_REQUIRED")
    if product_visual_custody.get("provider_product_reference_forbidden") is not True:
        raise ProviderCertificationError("PROFILE_CERTIFICATION_PROVIDER_PRODUCT_REFERENCE_FORBIDDEN")
    if not isinstance(profile_context, Mapping):
        raise ProviderCertificationError("PROFILE_CERTIFICATION_PROFILE_CONTEXT_REQUIRED")
    try:
        normalized = _profiles.normalize_approval_context(profile_context)
    except _profiles.ExecutionProfileError as exc:
        raise ProviderCertificationError(
            "PROFILE_CERTIFICATION_CONTEXT_INVALID",
            str(exc),
            details={"code": exc.code, "details": exc.details},
        ) from exc
    profile = normalized["duration_model_profile"]
    if (
        profile.get("provider") != "GOOGLE_FLOW"
        or profile.get("model") != "veo_3_1_lite"
        or int(profile.get("duration_s") or 0) != 8
        or profile.get("prompt_block_durations_s") != [8]
        or profile.get("aspect_ratio") != "9:16"
        or profile.get("generation_mode") != "SINGLE"
        or profile.get("execution_transport") != "GOOGLE_FLOW_CREATION_AGENT"
    ):
        raise ProviderCertificationError("PROFILE_CERTIFICATION_PROFILE_TUPLE_INVALID")
    if normalized.get("lane") != "FACELESS":
        raise ProviderCertificationError("PROFILE_CERTIFICATION_PROFILE_LANE_INVALID")
    return normalized


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _profile_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(row.get("profile_json") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        value = {}
    return value if isinstance(value, dict) else {}


async def provider_certification_status(profile: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve static or durable certification for this exact profile only."""

    canonical = _profiles.canonicalize_profile(profile)
    static = _profiles.provider_certification_status(canonical)
    if static.get("certified"):
        return static

    row = await _crud.get_by_profile_digest(canonical["profile_digest"])
    if row is None:
        return static
    stored = _profile_from_row(row)
    if _stable_json(stored) != _stable_json(canonical):
        return {
            "certified": False,
            "status": "NOT_CERTIFIED",
            "reason": "CERTIFICATION_PROFILE_CONTENT_MISMATCH",
            "profile_digest": canonical["profile_digest"],
            "record": row,
        }
    if _norm(row.get("status")).upper() != CERTIFICATION_CERTIFIED:
        return {
            "certified": False,
            "status": _norm(row.get("status")).upper() or "NOT_CERTIFIED",
            "reason": "PROVIDER_CERTIFICATION_NOT_ACCEPTED",
            "profile_digest": canonical["profile_digest"],
            "record": row,
        }
    return {
        "certified": True,
        "status": CERTIFICATION_CERTIFIED,
        "reason": None,
        "profile_digest": canonical["profile_digest"],
        "record": row,
        "source": "provider_execution_certification",
    }


def _reservation_values(
    *,
    profile: Mapping[str, Any],
    representative_lane: str,
    product_id: str,
    copy_id: str,
    product_digest: str,
    copy_digest: str,
    sweetwps_digest: str,
    compositor_digest: str,
    compiler_digest: str,
    lane_adapter_digest: str,
    runtime_sha: str,
    snapshot_id: str,
) -> dict[str, Any]:
    canonical = _profiles.canonicalize_profile(profile)
    required = {
        "profile_digest": canonical.get("profile_digest"),
        "provider": canonical.get("provider"),
        "model": canonical.get("model"),
        "duration_s": canonical.get("duration_s"),
        "aspect_ratio": canonical.get("aspect_ratio"),
        "audio_dialogue_route": canonical.get("audio_dialogue_route"),
        "provider_transport_key_provenance": canonical.get(
            "provider_transport_key_provenance"
        ),
        "capability_matrix_version": canonical.get("capability_matrix_version"),
        "execution_transport": canonical.get("execution_transport"),
        "generation_mode": canonical.get("generation_mode"),
        "execution_route": canonical.get("execution_route"),
        "product_id": product_id,
        "copy_id": copy_id,
        "product_digest": product_digest,
        "copy_digest": copy_digest,
        "sweetwps_digest": sweetwps_digest,
        "compositor_digest": compositor_digest,
        "compiler_digest": compiler_digest,
        "lane_adapter_digest": lane_adapter_digest,
        "runtime_sha": runtime_sha,
        "snapshot_id": snapshot_id,
    }
    if any(not _norm(value) for value in required.values()):
        missing = [key for key, value in required.items() if not _norm(value)]
        raise ProviderCertificationError(
            "CERTIFICATION_LINEAGE_INCOMPLETE",
            "All current profile and authority digests are required.",
            details={"missing": missing},
        )
    return {
        "certification_id": "pec_" + uuid.uuid4().hex[:20],
        "profile_digest": canonical["profile_digest"],
        "profile_json": _stable_json(canonical),
        "status": CERTIFICATION_RESERVED,
        "representative_lane": _norm(representative_lane).upper(),
        "provider": canonical["provider"],
        "model_key": canonical["model"],
        "duration_s": int(canonical["duration_s"]),
        "prompt_block_durations_json": _stable_json(
            canonical["prompt_block_durations_s"]
        ),
        "aspect_ratio": canonical["aspect_ratio"],
        "audio_dialogue_route": canonical["audio_dialogue_route"],
        "transport_key_provenance": canonical["provider_transport_key_provenance"],
        "capability_matrix_version": canonical["capability_matrix_version"],
        "execution_transport": canonical["execution_transport"],
        "generation_mode": canonical["generation_mode"],
        "execution_route": canonical["execution_route"],
        "product_id": _norm(product_id),
        "copy_id": _norm(copy_id),
        "product_digest": _norm(product_digest),
        "copy_digest": _norm(copy_digest),
        "sweetwps_digest": _norm(sweetwps_digest),
        "compositor_digest": _norm(compositor_digest),
        "compiler_digest": _norm(compiler_digest),
        "lane_adapter_digest": _norm(lane_adapter_digest),
        "runtime_sha": _norm(runtime_sha),
        "snapshot_id": _norm(snapshot_id),
        "created_at": _now(),
        "updated_at": _now(),
    }


async def reserve_capture(**kwargs: Any) -> tuple[dict[str, Any], bool]:
    """Reserve one exact profile; return (row, created)."""

    profile = kwargs.pop("profile")
    values = _reservation_values(profile=profile, **kwargs)
    existing = await _crud.get_by_profile_digest(values["profile_digest"])
    if existing is not None:
        # Self-heal a stale terminal reservation before deciding to reuse, so a
        # terminal linked job can never permanently occupy the shared provider
        # profile slot.  Provider-free; may transition the row to FAILED+reopenable
        # (archived + recreated just below) or leave it unchanged (active/pending).
        existing = await reconcile_stale_reservation(existing)
        existing_failure_code = _norm(existing.get("failure_code")).upper()
        if (
            _norm(existing.get("status")).upper() == CERTIFICATION_FAILED
            and existing_failure_code in _REOPENABLE_FAILURES
        ):
            reopened = await _crud.archive_failed_pre_provider_and_create_reservation(
                existing,
                values,
                reason=(
                    "EXPLICIT_NEW_CAPTURE_AFTER_UNSUITABLE_ARTIFACT_SUPERSEDE"
                    if existing_failure_code == CERTIFICATION_ARTIFACT_UNSUITABLE
                    else "EXPLICIT_NEW_CAPTURE_AFTER_PRE_PROVIDER_FAILURE"
                ),
            )
            # Under a concurrent reopen the CRUD may return a competitor's fresh
            # reservation rather than ours; only the caller that actually minted
            # the new row reports created=True, so exactly one capture ever fires.
            created = str(reopened.get("certification_id")) == str(
                values["certification_id"]
            )
            return reopened, created
        return existing, False
    try:
        return await _crud.create_reservation(values), True
    except Exception as exc:  # noqa: BLE001 — unique profile race is fail-closed
        existing = await _crud.get_by_profile_digest(values["profile_digest"])
        if existing is not None:
            return existing, False
        raise ProviderCertificationError(
            "CERTIFICATION_RESERVATION_FAILED",
            str(exc),
        ) from exc


async def mark_submitted(
    certification_id: str,
    *,
    job_id: str,
    snapshot_id: str,
) -> dict[str, Any]:
    row = await _crud.get_by_id(certification_id)
    if row is None:
        raise ProviderCertificationError("CERTIFICATION_NOT_FOUND")
    if row.get("status") == CERTIFICATION_CERTIFIED:
        return row
    if row.get("status") not in {CERTIFICATION_RESERVED, CERTIFICATION_SUBMITTED}:
        raise ProviderCertificationError(
            "CERTIFICATION_RESERVATION_NOT_OPEN",
            details={"status": row.get("status")},
        )
    return await _crud.update_certification(
        certification_id,
        status=CERTIFICATION_SUBMITTED,
        job_id=_norm(job_id),
        snapshot_id=_norm(snapshot_id),
    )


async def mark_failed(
    certification_id: str,
    *,
    code: str,
    detail: str = "",
    snapshot_id: str | None = None,
) -> dict[str, Any]:
    row = await _crud.get_by_id(certification_id)
    if row is None:
        raise ProviderCertificationError("CERTIFICATION_NOT_FOUND")
    if row.get("status") == CERTIFICATION_CERTIFIED:
        return row
    return await _crud.update_certification(
        certification_id,
        status=CERTIFICATION_FAILED,
        **({"snapshot_id": _norm(snapshot_id)} if _norm(snapshot_id) else {}),
        failure_code=_norm(code)[:160],
        failure_detail=_norm(detail)[:1000],
    )


async def supersede_unsuitable(
    certification_id: str,
    *,
    reason: str,
    superseded_by: str | None = None,
) -> dict[str, Any]:
    """Owner-authorized retirement of a submitted-but-unsuitable certification.

    A submitted capture whose artifact is unusable (e.g. a wrong-aspect video)
    cannot be finalized, yet its immutable job/snapshot/artifact lineage must be
    preserved.  This marks the row ``FAILED`` with the reopenable
    artifact-unsuitable code so the next exact-profile ``reserve_capture``
    archives the full prior row into the append-only history table and opens ONE
    fresh reservation.  No lineage column is nulled and no row is deleted; the
    supersede reason and replacement linkage are carried in ``failure_detail``
    for audit.  Fails closed on a promoted (CERTIFIED) certification.  Idempotent:
    superseding an already-superseded row returns it unchanged with no duplicate
    write.
    """

    row = await _crud.get_by_id(certification_id)
    if row is None:
        raise ProviderCertificationError("CERTIFICATION_NOT_FOUND")
    status = _norm(row.get("status")).upper()
    if status == CERTIFICATION_CERTIFIED:
        raise ProviderCertificationError(
            "CERTIFICATION_CERTIFIED_CANNOT_SUPERSEDE",
            details={"status": status},
        )
    if (
        status == CERTIFICATION_FAILED
        and _norm(row.get("failure_code")).upper() == CERTIFICATION_ARTIFACT_UNSUITABLE
    ):
        return row
    if status not in {
        CERTIFICATION_SUBMITTED,
        CERTIFICATION_RESERVED,
        CERTIFICATION_ARTIFACT_PENDING,
    }:
        raise ProviderCertificationError(
            "CERTIFICATION_NOT_SUPERSEDABLE",
            details={"status": status},
        )
    supersede_detail = "SUPERSEDED_UNSUITABLE:" + _stable_json(
        {
            "reason": _norm(reason)[:600],
            "superseded_at": _now(),
            "superseded_by": _norm(superseded_by),
        }
    )
    # ``mark_failed`` reuses ``update_certification`` for status/code/detail only,
    # so job_id/snapshot_id/artifact linkage columns are never touched.
    return await mark_failed(
        certification_id,
        code=CERTIFICATION_ARTIFACT_UNSUITABLE,
        detail=supersede_detail,
    )


async def reconcile_pre_provider_failure(
    certification_id: str,
    *,
    job_id: str,
    code: str,
    detail: str = "",
    snapshot_id: str | None = None,
) -> dict[str, Any]:
    """Close a certification whose linked job proved provider-free failure.

    The certification status remains the repository's existing terminal
    ``FAILED`` value; the pre-provider classification is carried in the
    failure code/detail so no schema mutation or fake proof record is needed.
    """

    row = await _crud.get_by_id(certification_id)
    if row is None:
        raise ProviderCertificationError("CERTIFICATION_NOT_FOUND")
    if _norm(row.get("job_id")) and _norm(row.get("job_id")) != _norm(job_id):
        raise ProviderCertificationError(
            "CERTIFICATION_JOB_MISMATCH",
            details={"expected": row.get("job_id"), "observed": job_id},
        )
    if row.get("status") == CERTIFICATION_CERTIFIED:
        raise ProviderCertificationError("CERTIFICATION_ALREADY_CERTIFIED")
    if row.get("status") == CERTIFICATION_FAILED:
        existing_snapshot_id = _norm(row.get("snapshot_id"))
        observed_snapshot_id = _norm(snapshot_id)
        if observed_snapshot_id and existing_snapshot_id not in ("", observed_snapshot_id):
            raise ProviderCertificationError(
                "CERTIFICATION_SNAPSHOT_MISMATCH",
                details={"expected": row.get("snapshot_id"), "observed": snapshot_id},
            )
        if observed_snapshot_id and not existing_snapshot_id:
            return await _crud.update_certification(
                certification_id,
                snapshot_id=observed_snapshot_id,
            )
        return row
    if snapshot_id and row.get("snapshot_id") not in (None, "", _norm(snapshot_id)):
        raise ProviderCertificationError(
            "CERTIFICATION_SNAPSHOT_MISMATCH",
            details={"expected": row.get("snapshot_id"), "observed": snapshot_id},
        )
    return await _crud.update_certification(
        certification_id,
        status=CERTIFICATION_FAILED,
        job_id=_norm(row.get("job_id") or job_id),
        **({"snapshot_id": _norm(snapshot_id)} if snapshot_id else {}),
        failure_code=_norm(code)[:160],
        failure_detail=_norm(detail)[:1000],
    )


# ---------------------------------------------------------------------------
# Provider-free stale-reservation reconciliation (self-healing state machine).
#
# ``reserve_capture`` is keyed by ``profile_digest`` and shares ONE reservation
# slot across every lane that resolves the same provider profile (e.g. HYBRID
# and FACELESS).  A reservation left SUBMITTED / ARTIFACT_PENDING whose linked
# job has already reached a terminal state would otherwise occupy that slot
# forever and permanently deadlock every sharing lane.  This classifies the
# linked job and reconciles it WITHOUT any provider generation call so a
# terminal linked job can never poison the shared provider profile.
# ---------------------------------------------------------------------------

# Linked-job statuses that are terminal for reconciliation.  This mirrors the
# generation lane's terminal set and additionally treats the delivery-failure
# status (which the generation lane does not itself list as generation-terminal)
# as terminal here, because a delivery failure with already-rendered bytes still
# leaves the certification permanently stuck.
_RECONCILE_TERMINAL_JOB_STATUSES = frozenset({
    "DONE",
    "PRODUCT_FIDELITY_REVIEW_REQUIRED",
    "FAILED",
    "REJECTED",
    "ARTIFACT_PERSISTENCE_FAILED",
    "DURABILITY_SYNC_FAILED",
    "RECOVERY_REQUIRED",
    "RECOVERY_UNRECOVERABLE",
    "GENERATED_BUT_UNRETRIEVED",
    "RENDER_NOT_MATERIALIZED",
    "STALE_OR_FOREIGN_CANDIDATES_ONLY",
    "FINAL_ARTIFACT_DELIVERY_FAILED",
})
_RECONCILE_SUCCESS_JOB_STATUSES = frozenset({"DONE"})


async def _resolve_linked_job_provider_free(job_id: str) -> dict[str, Any] | None:
    """Read one durable video job row + its persisted stage state.

    Pure repository read: no provider call and no reconcile-driven re-fetch, so
    it is safe inside the reservation path and never spends a credit.
    """
    if not job_id:
        return None
    try:
        from agent.db import crud
    except Exception:  # noqa: BLE001 — reconciliation must never hard-fail reserve
        return None
    try:
        row = await crud.get_video_production_job(job_id)
    except Exception:  # noqa: BLE001
        return None
    if not row:
        return None
    job: dict[str, Any] = {}
    try:
        state = json.loads(row.get("stage_state_json") or "{}")
        if isinstance(state, dict):
            job.update(state)
    except (TypeError, ValueError):
        pass
    # Authoritative DB columns win over any stale embedded stage state.
    for col in (
        "job_id", "status", "final_media_id", "final_local_path",
        "final_sha256", "product_id", "model", "aspect_ratio",
    ):
        if row.get(col) is not None:
            job[col] = row.get(col)
    return job


def _has_recoverable_artifact_bytes(job: Mapping[str, Any]) -> bool:
    """True only when a rendered artifact media id AND non-empty local bytes are
    both present on disk — the precondition for provider-free delivery recovery.
    """
    media_id = _norm(job.get("final_media_id") or job.get("media_id"))
    path = _norm(job.get("final_local_path") or job.get("local_path"))
    if not media_id or not path:
        for art in job.get("artifacts") or []:
            if not isinstance(art, Mapping):
                continue
            media_id = media_id or _norm(art.get("media_id"))
            path = path or _norm(art.get("local_path"))
    if not media_id or not path:
        return False
    try:
        import os

        return os.path.isfile(path) and os.path.getsize(path) > 0
    except Exception:  # noqa: BLE001
        return False


async def _attempt_provider_free_delivery_recovery(
    job_id: str,
) -> dict[str, Any] | None:
    """Re-register already-rendered on-disk bytes for a delivery-failed job.

    Delegates to the generation lane's local-only artifact registration, which
    never re-submits a provider generation.  Returns the re-read job on success,
    otherwise ``None`` so the caller supersedes and fires ONE corrected capture.
    """
    try:
        from agent.services.make_video import retry_artifact_delivery

        await retry_artifact_delivery(job_id)
    except Exception:  # noqa: BLE001 — recovery is best-effort; caller supersedes
        return None
    return await _resolve_linked_job_provider_free(job_id)


async def _try_finalize_recovered_artifact(
    certification_id: str, job: Mapping[str, Any]
) -> dict[str, Any] | None:
    """Promote a recovered artifact ONLY when the job already carries a PASSING
    frame-QC evidence block.

    Content frame-QC is an owner review step and is never fabricated here, so
    absent embedded PASS evidence this returns ``None`` and the caller
    supersedes so ONE corrected capture can fire.
    """
    frame_qc = job.get("frame_qc")
    if not isinstance(frame_qc, Mapping):
        frame_qc = job.get("frame_qc_evidence")
    if (
        not isinstance(frame_qc, Mapping)
        or _norm(frame_qc.get("status")).upper() != "PASS"
    ):
        return None
    try:
        return await finalize_capture(certification_id, job=job, frame_qc=frame_qc)
    except ProviderCertificationError:
        return None


async def reconcile_stale_reservation(
    existing: Mapping[str, Any],
) -> dict[str, Any]:
    """Provider-free reconciliation of a stale SUBMITTED / ARTIFACT_PENDING
    certification whose linked job has reached a terminal state.

    Returns the (possibly transitioned) certification row.  Invariants:
      * active / provider-ambiguous linked job  -> row UNCHANGED (reuse; never a
        duplicate submission)
      * terminal success awaiting owner finalize -> row UNCHANGED (reuse)
      * terminal pre-provider failure            -> row closed FAILED (reopenable)
      * terminal delivery failure with bytes     -> provider-free recovery first;
        a recovered + QC-passing artifact is finalized (zero new credit),
        otherwise the row is superseded (reopenable)
      * terminal provider-engaged failure, no bytes -> row superseded (reopenable)
      * a CERTIFIED row is never reached here and is never touched

    No provider generation call is ever made and no lineage is deleted.  The
    caller applies its existing FAILED+reopenable archive+recreate rule to any
    row this transitions.
    """
    row = dict(existing)
    status = _norm(row.get("status")).upper()
    if status not in {CERTIFICATION_SUBMITTED, CERTIFICATION_ARTIFACT_PENDING}:
        return row
    certification_id = _norm(row.get("certification_id"))
    job_id = _norm(row.get("job_id"))
    if not certification_id or not job_id:
        return row  # nothing linked to classify -> never duplicate

    job = await _resolve_linked_job_provider_free(job_id)
    if job is None:
        return row  # unresolvable linked job -> conservative reuse

    job_status = _norm(job.get("status")).upper()
    if job_status not in _RECONCILE_TERMINAL_JOB_STATUSES:
        return row  # (A) active / ambiguous provider op -> NEVER duplicate
    if job_status in _RECONCILE_SUCCESS_JOB_STATUSES:
        return row  # terminal success awaiting owner finalize -> reuse

    has_artifact = _has_recoverable_artifact_bytes(job)
    has_provider_op = bool(_provider_operation_id(job))

    if not has_artifact and not has_provider_op:
        # (B) terminal pre-provider failure -> close FAILED (reopenable)
        return await reconcile_pre_provider_failure(
            certification_id,
            job_id=job_id,
            code="PROFILE_CERTIFICATION_PRE_PROVIDER_FAILED",
            detail=f"RECONCILED_TERMINAL_PRE_PROVIDER:{job_status}"[:1000],
        )

    if has_artifact:
        # (C) terminal delivery failure with rendered bytes -> recover first.
        recovered = await _attempt_provider_free_delivery_recovery(job_id)
        if (
            recovered is not None
            and _norm(recovered.get("status")).upper() == "DONE"
        ):
            certified = await _try_finalize_recovered_artifact(
                certification_id, recovered
            )
            if certified is not None:
                return certified  # zero-new-credit certification via recovered bytes
        return await supersede_unsuitable(
            certification_id,
            reason=(
                f"RECONCILE_TERMINAL_DELIVERY_FAILURE:{job_status}:"
                f"recovered={'yes' if recovered is not None else 'no'}:"
                "content_qc_requires_owner_review"
            ),
            superseded_by="system-reconciler",
        )

    # (D) terminal provider-engaged failure, no recoverable bytes -> supersede.
    return await supersede_unsuitable(
        certification_id,
        reason=(
            f"RECONCILE_TERMINAL_ARTIFACT_UNRECOVERABLE:{job_status}:"
            "provider_op_no_bytes"
        ),
        superseded_by="system-reconciler",
    )


async def record_target_acknowledgement(
    certification_id: str,
    *,
    snapshot_id: str,
    acknowledgement: Mapping[str, Any],
) -> dict[str, Any]:
    """Carry the official snapshot acknowledgement onto certification lineage."""
    row = await _crud.get_by_id(certification_id)
    if row is None:
        raise ProviderCertificationError("CERTIFICATION_NOT_FOUND")
    if row.get("snapshot_id") != _norm(snapshot_id):
        raise ProviderCertificationError(
            "CERTIFICATION_SNAPSHOT_MISMATCH",
            details={"expected": row.get("snapshot_id"), "observed": snapshot_id},
        )
    digest = _norm(acknowledgement.get("target_digest"))
    if not digest or digest != _norm(acknowledgement.get("proposed_target_digest")):
        raise ProviderCertificationError("CERTIFICATION_TARGET_ACK_DIGEST_MISMATCH")
    existing_digest = _norm(row.get("target_ack_digest"))
    if existing_digest and existing_digest != digest:
        raise ProviderCertificationError(
            "CERTIFICATION_TARGET_ACK_STALE",
            details={"expected": existing_digest, "observed": digest},
        )
    return await _crud.update_certification(
        certification_id,
        target_ack_digest=digest,
        target_ack_json=_stable_json(dict(acknowledgement)),
        target_acknowledged_at=_now(),
    )


def _provider_operation_id(job: Mapping[str, Any]) -> str | None:
    for item in job.get("provider_operation_ids") or []:
        if isinstance(item, Mapping):
            item = (
                item.get("operation_id")
                or item.get("operation_name")
                or item.get("provider_operation_id")
                or item.get("name")
            )
        if _norm(item):
            return _norm(item)
    identity = job.get("generation_identity")
    if isinstance(identity, Mapping):
        for item in identity.get("operation_names") or []:
            if _norm(item):
                return _norm(item)
    for artifact in job.get("artifacts") or []:
        if not isinstance(artifact, Mapping):
            continue
        correlation = artifact.get("correlation") or {}
        if isinstance(correlation, Mapping):
            for key in ("provider_operation_id", "media_generation_id"):
                if _norm(correlation.get(key)):
                    return _norm(correlation.get(key))
        lineage = artifact.get("exact_product_lineage") or {}
        scene = lineage.get("provider_scene_artifact") if isinstance(lineage, Mapping) else None
        if isinstance(scene, Mapping):
            for key in ("provider_operation_id", "media_generation_id"):
                if _norm(scene.get(key)):
                    return _norm(scene.get(key))
    correlation = job.get("output_correlation") or {}
    if isinstance(correlation, Mapping):
        for key in ("provider_operation_id", "media_generation_id"):
            if _norm(correlation.get(key)):
                return _norm(correlation.get(key))
    return None


def _artifact_evidence(job: Mapping[str, Any], artifact: Mapping[str, Any]) -> dict[str, Any]:
    media_id = _norm(artifact.get("media_id") or job.get("media_id"))
    evidence = (job.get("artifact_file_evidence") or {}).get(media_id)
    if isinstance(evidence, Mapping) and _norm(evidence.get("sha256")):
        return dict(evidence)
    path = _norm(artifact.get("local_path") or job.get("local_path"))
    if path:
        try:
            from agent.services.video_artifact_delivery_service import file_delivery_evidence

            return file_delivery_evidence(path)
        except Exception:
            pass
    return {}


def _source_sha256(job: Mapping[str, Any], artifact: Mapping[str, Any]) -> str | None:
    lineage = artifact.get("exact_product_lineage")
    if not isinstance(lineage, Mapping):
        custody = job.get("product_visual_custody")
        lineage = custody.get("exact_video_composite") if isinstance(custody, Mapping) else None
    scene = lineage.get("provider_scene_artifact") if isinstance(lineage, Mapping) else None
    return _norm(scene.get("sha256")) if isinstance(scene, Mapping) else None


_FRAME_QC_FIELDS = (
    "product_visible_at_0_0s",
    "exactly_one_product",
    "no_product_flash",
    "no_identity_drift",
    "no_disappearance_or_replacement",
    "valid_custody_and_hands",
    "no_face_head_mouth",
    "dialogue_starts_at_0_0s",
    "dialogue_ends_inside_sweetwps",
    "no_terminal_dialogue_gap",
    "no_terminal_hallucination",
    "final_artifact_not_scene_scaffold",
    "active_route_proof",
)


async def finalize_capture(
    certification_id: str,
    *,
    job: Mapping[str, Any],
    frame_qc: Mapping[str, Any],
) -> dict[str, Any]:
    """Promote one completed artifact after strict evidence checks."""

    row = await _crud.get_by_id(certification_id)
    if row is None:
        raise ProviderCertificationError("CERTIFICATION_NOT_FOUND")
    if row.get("status") == CERTIFICATION_CERTIFIED:
        return row
    if row.get("status") not in {CERTIFICATION_SUBMITTED, CERTIFICATION_ARTIFACT_PENDING}:
        raise ProviderCertificationError(
            "CERTIFICATION_NOT_SUBMITTED",
            details={"status": row.get("status")},
        )
    if _norm(job.get("job_id")) != _norm(row.get("job_id")):
        raise ProviderCertificationError("CERTIFICATION_JOB_MISMATCH")
    if _norm(job.get("status")).upper() != "DONE":
        raise ProviderCertificationError(
            "CERTIFICATION_ARTIFACT_NOT_READY",
            details={"job_status": job.get("status"), "error": job.get("error")},
        )
    if not isinstance(frame_qc, Mapping) or _norm(frame_qc.get("status")).upper() != "PASS":
        raise ProviderCertificationError("FRAME_QC_NOT_PASSED")
    missing = [key for key in _FRAME_QC_FIELDS if frame_qc.get(key) is not True]
    if missing:
        raise ProviderCertificationError(
            "FRAME_QC_INCOMPLETE",
            details={"missing_or_false": missing},
        )

    artifacts = job.get("artifacts") or []
    artifact = artifacts[0] if artifacts and isinstance(artifacts[0], Mapping) else job
    evidence = _artifact_evidence(job, artifact)
    output_sha = _norm(
        evidence.get("sha256")
        or artifact.get("output_sha256")
        or job.get("output_sha256")
    )
    source_sha = _source_sha256(job, artifact)
    provider_operation_id = _provider_operation_id(job)
    media_id = _norm(artifact.get("media_id") or job.get("media_id"))
    if not provider_operation_id:
        raise ProviderCertificationError("PROVIDER_OPERATION_ID_UNPROVEN")
    if not media_id or not output_sha:
        raise ProviderCertificationError("ARTIFACT_OUTPUT_SHA_UNPROVEN")
    if not source_sha:
        raise ProviderCertificationError("PROVIDER_SCENE_SOURCE_SHA_UNPROVEN")
    if _norm(frame_qc.get("artifact_sha256")) != output_sha:
        raise ProviderCertificationError(
            "FRAME_QC_ARTIFACT_SHA_MISMATCH",
            details={"expected": output_sha, "observed": frame_qc.get("artifact_sha256")},
        )
    accounting = job.get("credit_accounting") or {}
    delta = accounting.get("delta")
    try:
        numeric_delta = float(delta)
    except (TypeError, ValueError):
        raise ProviderCertificationError("CREDIT_DELTA_UNPROVEN") from None
    profile = _profile_from_row(row)
    try:
        expected = float(
            ((profile.get("credits_cost_rule") or {}).get("profile_cost_ceiling"))
        )
    except (TypeError, ValueError):
        raise ProviderCertificationError("PROFILE_CREDIT_CEILING_UNPROVEN") from None
    # video_models.py defines a regular/typical price ceiling. Flow may debit
    # less because credits are promo-variable; only a negative or over-cap
    # delta is unexpected.
    if numeric_delta < 0 or numeric_delta > expected:
        raise ProviderCertificationError(
            "CREDIT_DELTA_UNEXPECTED",
            details={"expected": expected, "actual": numeric_delta},
        )
    qc_payload = dict(frame_qc)
    qc_payload["artifact_sha256"] = output_sha
    qc_payload["source_sha256"] = source_sha
    qc_payload["qc_receipt_sha256"] = _sha256(_stable_json(qc_payload))
    return await _crud.update_certification(
        certification_id,
        status=CERTIFICATION_CERTIFIED,
        provider_operation_id=provider_operation_id,
        artifact_media_id=media_id,
        source_sha256=source_sha,
        output_sha256=output_sha,
        credit_delta=numeric_delta,
        frame_qc_json=_stable_json(qc_payload),
    )


__all__ = [
    "CERTIFICATION_ARTIFACT_PENDING",
    "CERTIFICATION_ARTIFACT_UNSUITABLE",
    "CERTIFICATION_CERTIFIED",
    "CERTIFICATION_FAILED",
    "CERTIFICATION_RESERVED",
    "CERTIFICATION_SUBMITTED",
    "ProviderCertificationError",
    "finalize_capture",
    "mark_failed",
    "mark_submitted",
    "record_target_acknowledgement",
    "reconcile_pre_provider_failure",
    "provider_certification_status",
    "reserve_capture",
    "supersede_unsuitable",
    "validate_capture_contract",
]
