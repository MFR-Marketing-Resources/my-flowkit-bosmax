"""Provider-free stale-certification reconciliation state machine.

Regression proof for the owner directive: ``reserve_capture`` is keyed by
``profile_digest`` and shares ONE reservation slot across every lane resolving
the same provider profile (HYBRID and FACELESS both do).  A reservation left
SUBMITTED / ARTIFACT_PENDING whose linked job has reached a terminal state must
NEVER permanently occupy that slot.  The self-healing classifier:

  A. active / ambiguous provider op        -> reuse, no duplicate submission
  B. terminal pre-provider failure         -> FAILED/reopenable
  C. terminal delivery failure with bytes  -> provider-free recovery attempted
  D. recovered + QC-passing artifact        -> finalized (zero new credit)
  E. unrecoverable artifact                 -> supersede preserving lineage
  F. next reserve                           -> exactly ONE fresh reservation
  G. FACELESS stale row                     -> cannot deadlock HYBRID (shared digest)
  H. CERTIFIED                              -> immutable, never superseded
  I. reconciliation                         -> zero provider generation call
  J. concurrent reserve                     -> cannot create two fresh captures
"""

from __future__ import annotations

import asyncio

import pytest

from agent.db import provider_certification_crud as cert_crud
from agent.services import provider_certification_service as service
from agent.services import video_execution_profile_service as profiles


def _profile():
    return profiles.resolve_duration_model_profile(
        model="veo_3_1_lite",
        duration_s=8,
        aspect_ratio="9:16",
        logical_mode="T2V",
        source_mode="T2V",
        generation_mode="SINGLE",
        reference_count=0,
        prompt_block_count=1,
    )


def _reserve_kwargs(lane: str = "FACELESS"):
    return dict(
        representative_lane=lane,
        product_id="product-1",
        copy_id="copy-1",
        product_digest="product-digest",
        copy_digest="copy-digest",
        sweetwps_digest="sweetwps-digest",
        compositor_digest="compositor-digest",
        compiler_digest="compiler-digest",
        lane_adapter_digest="adapter-digest",
        runtime_sha="runtime-sha",
        snapshot_id="snapshot-1",
    )


def _async(value):
    async def resolve(*_a, **_k):
        return value

    return resolve


def _sub_row(**over):
    row = {
        "certification_id": "pec_test",
        "status": "SUBMITTED",
        "job_id": "g_job",
        "snapshot_id": "snap_1",
        "artifact_media_id": "media_1",
        "failure_code": None,
    }
    row.update(over)
    return row


def _forbid(counter, key):
    async def fn(*_a, **_k):
        counter[key] = counter.get(key, 0) + 1
        return {"status": "FAILED"}

    return fn


# --------------------------------------------------------------------------- #
# (A) active / ambiguous -> reuse, never duplicate
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_active_job_reuses_without_reconcile(monkeypatch):
    calls: dict = {}
    monkeypatch.setattr(
        service,
        "_resolve_linked_job_provider_free",
        _async({"job_id": "g_job", "status": "GENERATING"}),
    )
    monkeypatch.setattr(service, "supersede_unsuitable", _forbid(calls, "supersede"))
    monkeypatch.setattr(
        service, "reconcile_pre_provider_failure", _forbid(calls, "reconcile")
    )

    out = await service.reconcile_stale_reservation(_sub_row())

    assert out["status"] == "SUBMITTED"  # untouched
    assert calls == {}


# --------------------------------------------------------------------------- #
# (B) terminal pre-provider failure -> FAILED/reopenable
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_terminal_pre_provider_failure_reopens(monkeypatch):
    monkeypatch.setattr(
        service,
        "_resolve_linked_job_provider_free",
        _async({"job_id": "g_job", "status": "FAILED"}),  # no bytes, no provider op
    )
    captured: dict = {}

    async def fake_reconcile(cid, *, job_id, code, detail="", snapshot_id=None):
        captured.update(cid=cid, code=code, detail=detail)
        return {"certification_id": cid, "status": "FAILED", "failure_code": code}

    monkeypatch.setattr(service, "reconcile_pre_provider_failure", fake_reconcile)

    out = await service.reconcile_stale_reservation(_sub_row(artifact_media_id=None))

    assert out["status"] == service.CERTIFICATION_FAILED
    assert out["failure_code"] == "PROFILE_CERTIFICATION_PRE_PROVIDER_FAILED"
    assert out["failure_code"] in service._REOPENABLE_FAILURES
    assert captured["cid"] == "pec_test"


# --------------------------------------------------------------------------- #
# (C) terminal delivery failure with bytes -> recovery attempted, then supersede
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_delivery_failure_recovers_before_supersede(tmp_path, monkeypatch):
    mp4 = tmp_path / "art.mp4"
    mp4.write_bytes(b"\x00" * 1024)
    job = {
        "job_id": "g_job",
        "status": "FINAL_ARTIFACT_DELIVERY_FAILED",
        "final_media_id": "media_1",
        "final_local_path": str(mp4),
    }
    monkeypatch.setattr(service, "_resolve_linked_job_provider_free", _async(job))

    recovery = {"n": 0}

    async def fake_recovery(job_id):
        recovery["n"] += 1
        # recovery ran but the artifact did not reach a certifiable DONE state
        return {**job}

    monkeypatch.setattr(
        service, "_attempt_provider_free_delivery_recovery", fake_recovery
    )

    sup: dict = {}

    async def fake_supersede(cid, *, reason, superseded_by=None):
        sup.update(cid=cid, reason=reason, by=superseded_by)
        return {
            "certification_id": cid,
            "status": "FAILED",
            "failure_code": service.CERTIFICATION_ARTIFACT_UNSUITABLE,
        }

    monkeypatch.setattr(service, "supersede_unsuitable", fake_supersede)

    out = await service.reconcile_stale_reservation(_sub_row())

    assert recovery["n"] == 1  # recover BEFORE regenerate
    assert out["failure_code"] == service.CERTIFICATION_ARTIFACT_UNSUITABLE
    assert sup["reason"].startswith("RECONCILE_TERMINAL_DELIVERY_FAILURE")
    assert sup["by"] == "system-reconciler"


# --------------------------------------------------------------------------- #
# (D) recovered artifact can proceed to certification finalization
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_recovered_artifact_finalizes_and_certifies(tmp_path, monkeypatch):
    mp4 = tmp_path / "art.mp4"
    mp4.write_bytes(b"\x00" * 1024)
    delivery_failed = {
        "job_id": "g_job",
        "status": "FINAL_ARTIFACT_DELIVERY_FAILED",
        "final_media_id": "media_1",
        "final_local_path": str(mp4),
    }
    monkeypatch.setattr(
        service, "_resolve_linked_job_provider_free", _async(delivery_failed)
    )

    recovered = {
        "job_id": "g_job",
        "status": "DONE",
        "final_media_id": "media_1",
        "final_local_path": str(mp4),
        "frame_qc": {"status": "PASS"},
    }
    monkeypatch.setattr(
        service, "_attempt_provider_free_delivery_recovery", _async(recovered)
    )

    fin: dict = {}

    async def fake_finalize(cid, *, job, frame_qc):
        fin.update(cid=cid, qc=dict(frame_qc), job_status=job.get("status"))
        return {"certification_id": cid, "status": "CERTIFIED"}

    monkeypatch.setattr(service, "finalize_capture", fake_finalize)

    out = await service.reconcile_stale_reservation(_sub_row())

    assert out["status"] == "CERTIFIED"
    assert fin["cid"] == "pec_test"
    assert fin["job_status"] == "DONE"


# --------------------------------------------------------------------------- #
# (E) unrecoverable artifact -> supersede preserving lineage
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_unrecoverable_artifact_supersedes_preserving_lineage(monkeypatch):
    monkeypatch.setattr(
        service,
        "_resolve_linked_job_provider_free",
        _async(
            {
                "job_id": "g_job",
                "status": "RECOVERY_UNRECOVERABLE",
                "provider_operation_ids": ["op_123"],  # provider engaged, no bytes
            }
        ),
    )

    sup: dict = {}

    async def fake_supersede(cid, *, reason, superseded_by=None):
        sup.update(cid=cid, reason=reason)
        # supersede never nulls lineage columns
        return {
            "certification_id": cid,
            "status": "FAILED",
            "failure_code": service.CERTIFICATION_ARTIFACT_UNSUITABLE,
            "job_id": "g_job",
            "snapshot_id": "snap_1",
            "artifact_media_id": "media_1",
        }

    monkeypatch.setattr(service, "supersede_unsuitable", fake_supersede)

    out = await service.reconcile_stale_reservation(_sub_row())

    assert sup["reason"].startswith("RECONCILE_TERMINAL_ARTIFACT_UNRECOVERABLE")
    assert out["job_id"] == "g_job"
    assert out["snapshot_id"] == "snap_1"
    assert out["artifact_media_id"] == "media_1"


# --------------------------------------------------------------------------- #
# (H) CERTIFIED is immutable: short-circuits before any classification
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_certified_row_is_never_reconciled(monkeypatch):
    calls: dict = {}
    monkeypatch.setattr(service, "supersede_unsuitable", _forbid(calls, "supersede"))
    monkeypatch.setattr(
        service, "reconcile_pre_provider_failure", _forbid(calls, "reconcile")
    )

    async def spy_resolve(job_id):
        calls["resolve"] = calls.get("resolve", 0) + 1
        return {"status": "FAILED"}

    monkeypatch.setattr(service, "_resolve_linked_job_provider_free", spy_resolve)

    out = await service.reconcile_stale_reservation(
        {"certification_id": "pec_cert", "status": "CERTIFIED", "job_id": "g_job"}
    )

    assert out["status"] == "CERTIFIED"
    assert calls == {}  # no resolve, no supersede, no reconcile


# --------------------------------------------------------------------------- #
# (I) reconciliation makes no provider generation call
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_reconciliation_makes_no_provider_generation_call(tmp_path, monkeypatch):
    mp4 = tmp_path / "a.mp4"
    mp4.write_bytes(b"\x00" * 512)
    monkeypatch.setattr(
        service,
        "_resolve_linked_job_provider_free",
        _async(
            {
                "job_id": "g_job",
                "status": "FINAL_ARTIFACT_DELIVERY_FAILED",
                "final_media_id": "m",
                "final_local_path": str(mp4),
            }
        ),
    )

    from agent.services import make_video

    calls = {"retry": 0}

    async def fake_retry(job_id):
        calls["retry"] += 1
        return {}

    async def forbidden(*_a, **_k):
        raise AssertionError("provider generation call during reconciliation")

    # the ONLY make_video hook the recovery may touch is local re-registration
    monkeypatch.setattr(make_video, "retry_artifact_delivery", fake_retry)
    monkeypatch.setattr(make_video, "start_generate", forbidden)
    monkeypatch.setattr(
        service,
        "supersede_unsuitable",
        _async(
            {
                "certification_id": "pec_test",
                "status": "FAILED",
                "failure_code": service.CERTIFICATION_ARTIFACT_UNSUITABLE,
            }
        ),
    )

    out = await service.reconcile_stale_reservation(_sub_row())

    assert calls["retry"] == 1  # provider-free local re-registration only
    assert out["failure_code"] == service.CERTIFICATION_ARTIFACT_UNSUITABLE


# --------------------------------------------------------------------------- #
# (F) next reserve reopens exactly once, then reuses (real DB)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_reserve_after_terminal_job_reopens_exactly_once(monkeypatch):
    profile = _profile()
    kwargs = _reserve_kwargs()

    first, created = await service.reserve_capture(profile=profile, **kwargs)
    assert created is True
    first_id = first["certification_id"]
    await service.mark_submitted(first_id, job_id="g_term_f", snapshot_id="snap_f")

    monkeypatch.setattr(
        service,
        "_resolve_linked_job_provider_free",
        _async({"job_id": "g_term_f", "status": "FAILED"}),
    )

    second, created_again = await service.reserve_capture(profile=profile, **kwargs)
    assert created_again is True
    assert second["certification_id"] != first_id
    assert second["status"] == service.CERTIFICATION_RESERVED
    assert await cert_crud.get_by_id(first_id) is None  # archived, not destroyed

    third, created_third = await service.reserve_capture(profile=profile, **kwargs)
    assert created_third is False  # fresh RESERVED row reused, no duplicate
    assert third["certification_id"] == second["certification_id"]


# --------------------------------------------------------------------------- #
# (G) FACELESS stale reservation cannot deadlock HYBRID on the shared digest
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_faceless_stale_does_not_deadlock_hybrid(tmp_path, monkeypatch):
    profile = _profile()

    faceless, created = await service.reserve_capture(
        profile=profile, **_reserve_kwargs("FACELESS")
    )
    assert created is True
    faceless_id = faceless["certification_id"]
    faceless_digest = faceless["profile_digest"]
    await service.mark_submitted(
        faceless_id, job_id="g_faceless_g", snapshot_id="snap_g"
    )

    mp4 = tmp_path / "faceless.mp4"
    mp4.write_bytes(b"\x00" * 2048)
    monkeypatch.setattr(
        service,
        "_resolve_linked_job_provider_free",
        _async(
            {
                "job_id": "g_faceless_g",
                "status": "FINAL_ARTIFACT_DELIVERY_FAILED",
                "final_media_id": "m_g",
                "final_local_path": str(mp4),
            }
        ),
    )
    # recovery cannot reach a certifiable DONE state -> supersede path
    monkeypatch.setattr(
        service,
        "_attempt_provider_free_delivery_recovery",
        _async({"job_id": "g_faceless_g", "status": "FINAL_ARTIFACT_DELIVERY_FAILED"}),
    )

    hybrid, hybrid_created = await service.reserve_capture(
        profile=profile, **_reserve_kwargs("HYBRID")
    )

    assert hybrid_created is True  # NOT deadlocked into reuse
    assert hybrid["certification_id"] != faceless_id
    assert hybrid["status"] == service.CERTIFICATION_RESERVED
    assert hybrid["profile_digest"] == faceless_digest
    assert await cert_crud.get_by_id(faceless_id) is None  # archived


# --------------------------------------------------------------------------- #
# (J) concurrent reserve cannot create two fresh captures
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_concurrent_reserve_creates_exactly_one_fresh(monkeypatch):
    profile = _profile()
    kwargs = _reserve_kwargs()

    first, created = await service.reserve_capture(profile=profile, **kwargs)
    assert created is True
    first_id = first["certification_id"]
    await service.mark_submitted(first_id, job_id="g_term_j", snapshot_id="snap_j")

    monkeypatch.setattr(
        service,
        "_resolve_linked_job_provider_free",
        _async({"job_id": "g_term_j", "status": "FAILED"}),
    )

    results = await asyncio.gather(
        service.reserve_capture(profile=profile, **kwargs),
        service.reserve_capture(profile=profile, **kwargs),
        service.reserve_capture(profile=profile, **kwargs),
    )

    ids = {row["certification_id"] for row, _ in results}
    assert len(ids) == 1  # all callers converge on ONE fresh reservation
    assert first_id not in ids  # the stale row was reopened, not reused
    # exactly one live reservation exists for the shared profile digest
    live = await cert_crud.get_by_profile_digest(first["profile_digest"])
    assert live is not None
    assert live["certification_id"] in ids


# --------------------------------------------------------------------------- #
# (K) credit-free pre-provider dispatch rejection is reopenable
# --------------------------------------------------------------------------- #
def test_pre_provider_dispatch_rejection_is_reopenable():
    # FAILED with a non-reopenable code but NO provider evidence (never
    # dispatched) — a bounded contract-validation rejection, credit-free.
    row = {
        "status": "FAILED",
        "failure_code": "PROFILE_CERTIFICATION_SURFACE_MUST_BE_FACELESS",
        "job_id": None,
        "provider_operation_id": None,
        "artifact_media_id": None,
        "credit_delta": None,
    }
    assert service._failed_reservation_is_reopenable(row) is True


def test_failed_with_linked_job_is_not_reopenable_by_evidence_rule():
    row = {
        "status": "FAILED",
        "failure_code": "SOME_TERMINAL_PROVIDER_FAILURE",
        "job_id": "g_x",  # engaged the provider lane
    }
    assert service._failed_reservation_is_reopenable(row) is False


def test_failed_with_credit_or_artifact_is_not_reopenable():
    assert (
        service._failed_reservation_is_reopenable(
            {"status": "FAILED", "failure_code": "X", "credit_delta": 5}
        )
        is False
    )
    assert (
        service._failed_reservation_is_reopenable(
            {"status": "FAILED", "failure_code": "X", "artifact_media_id": "m1"}
        )
        is False
    )
    assert (
        service._failed_reservation_is_reopenable(
            {"status": "FAILED", "failure_code": "X", "provider_operation_id": "op1"}
        )
        is False
    )


def test_explicit_reopenable_code_reopens_even_with_evidence():
    row = {
        "status": "FAILED",
        "failure_code": service.CERTIFICATION_ARTIFACT_UNSUITABLE,
        "job_id": "g_x",
        "credit_delta": 5,
    }
    assert service._failed_reservation_is_reopenable(row) is True


def test_non_failed_is_not_reopenable():
    assert service._failed_reservation_is_reopenable({"status": "RESERVED"}) is False
    assert service._failed_reservation_is_reopenable({"status": "SUBMITTED"}) is False


@pytest.mark.asyncio
async def test_reserve_reopens_after_pre_provider_dispatch_rejection(monkeypatch):
    profile = _profile()
    kwargs = _reserve_kwargs()

    first, created = await service.reserve_capture(profile=profile, **kwargs)
    assert created is True
    first_id = first["certification_id"]
    # a bounded pre-provider dispatch rejection: FAILED, non-reopenable code,
    # never dispatched (no provider evidence)
    await cert_crud.update_certification(
        first_id,
        status="FAILED",
        failure_code="PROFILE_CERTIFICATION_SURFACE_MUST_BE_FACELESS",
        failure_detail="rejected before any provider call",
    )

    second, created_again = await service.reserve_capture(profile=profile, **kwargs)
    assert created_again is True
    assert second["certification_id"] != first_id
    assert second["status"] == service.CERTIFICATION_RESERVED
    assert await cert_crud.get_by_id(first_id) is None  # archived, not destroyed
