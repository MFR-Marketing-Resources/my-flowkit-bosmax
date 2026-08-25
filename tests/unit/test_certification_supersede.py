"""Owner-authorized supersede of a submitted-but-unsuitable certification.

Covers the service contract (fail-closed on CERTIFIED, idempotent reopen,
immutable job/snapshot/artifact lineage) plus the real-DB proof that a fresh
``reserve_capture`` for the same profile ARCHIVES the superseded row into the
append-only history table (relocated, never destroyed) and opens one new
reservation.  Also covers the Faceless supersede HTTP endpoint contract.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agent.api import faceless as api
from agent.db import provider_certification_crud as cert_crud
from agent.db import schema
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


def _reserve_kwargs():
    return dict(
        representative_lane="FACELESS",
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


def _async_fn(value):
    async def resolve(*_args, **_kwargs):
        return value

    return resolve


def _owner():
    return SimpleNamespace(
        staff_id="staff_test_owner",
        role_codes=("OWNER",),
        permission_codes=("production.execute",),
    )


# --------------------------------------------------------------------------- #
# Service contract
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_supersede_submitted_marks_failed_and_preserves_linkage(monkeypatch):
    row = {
        "certification_id": "pec_sub",
        "status": "SUBMITTED",
        "job_id": "g_job",
        "snapshot_id": "snap_1",
        "artifact_media_id": "media_1",
    }
    captured: dict = {}

    async def update_certification(_id, **values):
        captured.update(values)
        return {**row, **values}

    monkeypatch.setattr(service._crud, "get_by_id", _async_fn(row))
    monkeypatch.setattr(service._crud, "update_certification", update_certification)

    result = await service.supersede_unsuitable(
        "pec_sub", reason="wrong aspect ratio 16:9", superseded_by="staff_test_owner"
    )

    assert result["status"] == service.CERTIFICATION_FAILED
    assert result["failure_code"] == service.CERTIFICATION_ARTIFACT_UNSUITABLE
    # reopenable so the next capture archives+recreates
    assert service.CERTIFICATION_ARTIFACT_UNSUITABLE in service._REOPENABLE_FAILURES
    # immutable lineage: the write never touched job/snapshot/artifact columns
    assert "job_id" not in captured
    assert "snapshot_id" not in captured
    assert "artifact_media_id" not in captured
    assert result["job_id"] == "g_job"
    assert result["snapshot_id"] == "snap_1"
    assert result["artifact_media_id"] == "media_1"
    # supersede reason recorded for audit
    assert result["failure_detail"].startswith("SUPERSEDED_UNSUITABLE:")
    assert "wrong aspect ratio 16:9" in result["failure_detail"]
    assert "staff_test_owner" in result["failure_detail"]


@pytest.mark.asyncio
async def test_supersede_certified_fails_closed(monkeypatch):
    row = {"certification_id": "pec_cert", "status": "CERTIFIED"}
    updated = {"called": False}

    async def update_certification(_id, **values):
        updated["called"] = True
        return row

    monkeypatch.setattr(service._crud, "get_by_id", _async_fn(row))
    monkeypatch.setattr(service._crud, "update_certification", update_certification)

    with pytest.raises(service.ProviderCertificationError) as exc:
        await service.supersede_unsuitable("pec_cert", reason="anything")

    assert exc.value.code == "CERTIFICATION_CERTIFIED_CANNOT_SUPERSEDE"
    assert updated["called"] is False


@pytest.mark.asyncio
async def test_supersede_rejects_non_open_status(monkeypatch):
    row = {"certification_id": "pec_x", "status": "FAILED", "failure_code": "PROVIDER_REJECTED"}
    monkeypatch.setattr(service._crud, "get_by_id", _async_fn(row))

    with pytest.raises(service.ProviderCertificationError) as exc:
        await service.supersede_unsuitable("pec_x", reason="anything")

    assert exc.value.code == "CERTIFICATION_NOT_SUPERSEDABLE"
    assert exc.value.details == {"status": "FAILED"}


@pytest.mark.asyncio
async def test_supersede_is_idempotent(monkeypatch):
    state = {
        "row": {
            "certification_id": "pec_idem",
            "status": "SUBMITTED",
            "job_id": "g_job",
            "snapshot_id": "snap_1",
        }
    }
    update_calls = {"count": 0}

    async def get_by_id(_id):
        return dict(state["row"])

    async def update_certification(_id, **values):
        update_calls["count"] += 1
        state["row"] = {**state["row"], **values}
        return dict(state["row"])

    monkeypatch.setattr(service._crud, "get_by_id", get_by_id)
    monkeypatch.setattr(service._crud, "update_certification", update_certification)

    first = await service.supersede_unsuitable("pec_idem", reason="wrong aspect")
    second = await service.supersede_unsuitable("pec_idem", reason="wrong aspect again")

    assert first["status"] == service.CERTIFICATION_FAILED
    assert first["failure_code"] == service.CERTIFICATION_ARTIFACT_UNSUITABLE
    # same terminal row, no error, no duplicate write
    assert second["certification_id"] == first["certification_id"]
    assert second["status"] == service.CERTIFICATION_FAILED
    assert second["failure_code"] == service.CERTIFICATION_ARTIFACT_UNSUITABLE
    assert update_calls["count"] == 1
    # original supersede reason preserved, not overwritten by the second call
    assert "wrong aspect" in second["failure_detail"]
    assert "again" not in second["failure_detail"]


@pytest.mark.asyncio
async def test_supersede_missing_row_is_not_found(monkeypatch):
    monkeypatch.setattr(service._crud, "get_by_id", _async_fn(None))
    with pytest.raises(service.ProviderCertificationError) as exc:
        await service.supersede_unsuitable("pec_missing", reason="x")
    assert exc.value.code == "CERTIFICATION_NOT_FOUND"


# --------------------------------------------------------------------------- #
# Real-DB lineage proof: reserve after supersede archives, never deletes
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_reserve_after_supersede_archives_lineage_and_reopens():
    profile = _profile()
    kwargs = _reserve_kwargs()

    first, created = await service.reserve_capture(profile=profile, **kwargs)
    assert created is True
    first_id = first["certification_id"]
    profile_digest = first["profile_digest"]

    # advance to SUBMITTED with real job + snapshot linkage
    await service.mark_submitted(first_id, job_id="g_job_1", snapshot_id="snap_1")

    superseded = await service.supersede_unsuitable(
        first_id, reason="wrong aspect ratio 16:9", superseded_by="staff_test_owner"
    )
    assert superseded["status"] == service.CERTIFICATION_FAILED
    assert superseded["failure_code"] == service.CERTIFICATION_ARTIFACT_UNSUITABLE
    # linkage intact after supersede
    assert superseded["job_id"] == "g_job_1"
    assert superseded["snapshot_id"] == "snap_1"

    # a fresh capture for the SAME profile reopens: archive old, new reservation
    second, created_again = await service.reserve_capture(profile=profile, **kwargs)
    assert created_again is True
    assert second["certification_id"] != first_id
    assert second["status"] == service.CERTIFICATION_RESERVED
    assert second["profile_digest"] == profile_digest

    # the old row was RELOCATED to append-only history, not destroyed
    assert await cert_crud.get_by_id(first_id) is None
    db = await schema.get_db()
    cursor = await db.execute(
        "SELECT history_id, certification_id, profile_digest, row_json, archive_reason "
        "FROM provider_execution_certification_history WHERE certification_id=?",
        (first_id,),
    )
    history = [dict(entry) for entry in await cursor.fetchall()]
    await cursor.close()
    assert len(history) == 1
    archived = history[0]
    assert archived["profile_digest"] == profile_digest
    assert archived["archive_reason"] == "EXPLICIT_NEW_CAPTURE_AFTER_UNSUITABLE_ARTIFACT_SUPERSEDE"
    # the full prior row — including job/snapshot lineage and supersede reason —
    # is preserved verbatim in history
    prior = json.loads(archived["row_json"])
    assert prior["status"] == "FAILED"
    assert prior["failure_code"] == service.CERTIFICATION_ARTIFACT_UNSUITABLE
    assert prior["job_id"] == "g_job_1"
    assert prior["snapshot_id"] == "snap_1"
    assert "wrong aspect ratio 16:9" in prior["failure_detail"]


# --------------------------------------------------------------------------- #
# HTTP endpoint contract
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_endpoint_success_returns_status_and_certification(monkeypatch):
    monkeypatch.setattr(api, "_require_profile_certification_owner", _owner)
    monkeypatch.setattr(
        cert_crud,
        "get_by_id",
        _async_fn({"certification_id": "pec_ok", "profile_digest": "digest-A", "status": "SUBMITTED"}),
    )
    captured: dict = {}

    async def fake_supersede(cid, *, reason, superseded_by=None):
        captured["cid"] = cid
        captured["reason"] = reason
        captured["by"] = superseded_by
        return {
            "certification_id": cid,
            "status": "FAILED",
            "failure_code": service.CERTIFICATION_ARTIFACT_UNSUITABLE,
        }

    monkeypatch.setattr(service, "supersede_unsuitable", fake_supersede)

    result = await api.supersede_faceless_profile_certification(
        api.FacelessProfileCertificationSupersedeRequest(
            certification_id="pec_ok", reason="wrong aspect", profile_digest="digest-A"
        )
    )

    assert result["status"] == "FAILED"
    assert result["certification"]["certification_id"] == "pec_ok"
    assert captured == {"cid": "pec_ok", "reason": "wrong aspect", "by": "staff_test_owner"}


@pytest.mark.asyncio
async def test_endpoint_rejects_profile_digest_mismatch(monkeypatch):
    monkeypatch.setattr(api, "_require_profile_certification_owner", _owner)
    monkeypatch.setattr(
        cert_crud,
        "get_by_id",
        _async_fn({"certification_id": "pec_x", "profile_digest": "digest-A", "status": "SUBMITTED"}),
    )
    called = {"supersede": False}

    async def fake_supersede(*_args, **_kwargs):
        called["supersede"] = True
        return {}

    monkeypatch.setattr(service, "supersede_unsuitable", fake_supersede)

    with pytest.raises(HTTPException) as raised:
        await api.supersede_faceless_profile_certification(
            api.FacelessProfileCertificationSupersedeRequest(
                certification_id="pec_x", reason="wrong", profile_digest="digest-B"
            )
        )

    assert raised.value.status_code == 409
    assert raised.value.detail["error_code"] == "PROFILE_CERTIFICATION_DIGEST_MISMATCH"
    assert called["supersede"] is False


@pytest.mark.asyncio
async def test_endpoint_missing_certification_is_404(monkeypatch):
    monkeypatch.setattr(api, "_require_profile_certification_owner", _owner)
    monkeypatch.setattr(cert_crud, "get_by_id", _async_fn(None))

    with pytest.raises(HTTPException) as raised:
        await api.supersede_faceless_profile_certification(
            api.FacelessProfileCertificationSupersedeRequest(
                certification_id="pec_missing", reason="wrong", profile_digest="digest-A"
            )
        )

    assert raised.value.status_code == 404


@pytest.mark.asyncio
async def test_endpoint_maps_certified_error_to_409(monkeypatch):
    monkeypatch.setattr(api, "_require_profile_certification_owner", _owner)
    monkeypatch.setattr(
        cert_crud,
        "get_by_id",
        _async_fn({"certification_id": "pec_cert", "profile_digest": "digest-A", "status": "CERTIFIED"}),
    )

    async def raise_certified(_cid, *, reason, superseded_by=None):
        raise service.ProviderCertificationError(
            "CERTIFICATION_CERTIFIED_CANNOT_SUPERSEDE", details={"status": "CERTIFIED"}
        )

    monkeypatch.setattr(service, "supersede_unsuitable", raise_certified)

    with pytest.raises(HTTPException) as raised:
        await api.supersede_faceless_profile_certification(
            api.FacelessProfileCertificationSupersedeRequest(
                certification_id="pec_cert", reason="wrong", profile_digest="digest-A"
            )
        )

    assert raised.value.status_code == 409
    assert raised.value.detail["error_code"] == "CERTIFICATION_CERTIFIED_CANNOT_SUPERSEDE"
    assert raised.value.detail["details"] == {"status": "CERTIFIED"}
