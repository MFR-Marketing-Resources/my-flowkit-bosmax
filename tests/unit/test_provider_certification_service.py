"""Focused contracts for active shared profile certification."""

from types import SimpleNamespace

import pytest

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


def _context(profile):
    return profiles.build_approval_context(
        profile,
        lane="FACELESS",
        product_digest="product-digest",
        copy_digest="copy-digest",
        sweetwps_digest_value="sweetwps-digest",
        compositor_digest_value="compositor-digest",
        compiler_digest_value="compiler-digest",
        adapter_digest="adapter-digest",
    )


def test_capture_contract_is_owner_only_and_active_t2v():
    profile = _profile()
    context = _context(profile)
    owner = SimpleNamespace(
        role_codes=("OWNER",), permission_codes=("production.execute",)
    )
    normalized = service.validate_capture_contract(
        profile_context=context,
        mode="T2V",
        source_mode="T2V",
        model="veo_3_1_lite",
        duration_s=8,
        aspect="9:16",
        num_videos=1,
        image_media_ids=[],
        product_id="product-1",
        production_recipe="FACELESS",
        surface_lane="FACELESS",
        product_visual_custody={
            "provider_route": "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE",
            "provider_product_reference_forbidden": True,
        },
        confirm_live_credit_burn=True,
        maximum_provider_operations=1,
        max_retry_operations=0,
        auth_context=owner,
    )
    assert normalized["lane"] == "FACELESS"
    assert normalized["duration_model_profile"]["prompt_block_durations_s"] == [8]

    with pytest.raises(service.ProviderCertificationError) as exc:
        service.validate_capture_contract(
            profile_context=context,
            mode="F2V",
            source_mode="HYBRID",
            model="veo_3_1_lite",
            duration_s=8,
            aspect="9:16",
            num_videos=1,
            image_media_ids=[],
            product_id="product-1",
            production_recipe="HYBRID",
            surface_lane="HYBRID",
            product_visual_custody={
                "provider_route": "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE",
                "provider_product_reference_forbidden": True,
            },
            confirm_live_credit_burn=True,
            maximum_provider_operations=1,
            max_retry_operations=0,
            auth_context=owner,
        )
    assert exc.value.code == "PROFILE_CERTIFICATION_MODE_MUST_BE_T2V"


@pytest.mark.asyncio
async def test_certification_status_is_shared_by_profile_digest(monkeypatch):
    profile = _profile()
    row = {
        "status": "CERTIFIED",
        "profile_digest": profile["profile_digest"],
        "profile_json": service._stable_json(profile),
        "provider_operation_id": "operations/one",
    }
    monkeypatch.setattr(
        profiles,
        "provider_certification_status",
        lambda _profile: {
            "certified": False,
            "status": "NOT_CERTIFIED",
            "reason": "NO_PROVIDER_CERTIFICATION_FOR_PROFILE",
            "profile_digest": profile["profile_digest"],
        },
    )
    monkeypatch.setattr(service._crud, "get_by_profile_digest", lambda _digest: _async(row))
    result = await service.provider_certification_status(profile)
    assert result["certified"] is True
    assert result["source"] == "provider_execution_certification"
    assert result["record"]["provider_operation_id"] == "operations/one"


@pytest.mark.asyncio
async def test_stale_profile_content_does_not_reuse_digest_record(monkeypatch):
    profile = _profile()
    stale = dict(profile)
    stale["aspect_ratio"] = "16:9"
    row = {
        "status": "CERTIFIED",
        "profile_digest": profile["profile_digest"],
        "profile_json": service._stable_json(stale),
    }
    monkeypatch.setattr(
        profiles,
        "provider_certification_status",
        lambda _profile: {
            "certified": False,
            "status": "NOT_CERTIFIED",
            "reason": "NO_PROVIDER_CERTIFICATION_FOR_PROFILE",
            "profile_digest": profile["profile_digest"],
        },
    )
    monkeypatch.setattr(service._crud, "get_by_profile_digest", lambda _digest: _async(row))
    result = await service.provider_certification_status(profile)
    assert result["certified"] is False
    assert result["reason"] == "CERTIFICATION_PROFILE_CONTENT_MISMATCH"


@pytest.mark.asyncio
async def test_pre_provider_failure_allows_one_new_archived_reservation(monkeypatch):
    profile = _profile()
    values = service._reservation_values(
        profile=profile,
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
    )
    existing = dict(values, status="FAILED", failure_code="FLOW_EDITOR_BINDING_REQUIRED")
    replacement = dict(values, certification_id="pec_new", status="RESERVED")
    monkeypatch.setattr(service._crud, "get_by_profile_digest", lambda _digest: _async(existing))
    monkeypatch.setattr(
        service._crud,
        "archive_failed_pre_provider_and_create_reservation",
        lambda *_args, **_kwargs: _async(replacement),
    )
    row, created = await service.reserve_capture(
        profile=profile,
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
    )
    assert created is True
    assert row["certification_id"] == "pec_new"


@pytest.mark.asyncio
async def test_provider_failure_is_not_reopened(monkeypatch):
    profile = _profile()
    values = service._reservation_values(
        profile=profile,
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
    )
    existing = dict(values, status="FAILED", failure_code="PROVIDER_REJECTED")
    monkeypatch.setattr(service._crud, "get_by_profile_digest", lambda _digest: _async(existing))
    row, created = await service.reserve_capture(
        profile=profile,
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
    )
    assert created is False
    assert row["failure_code"] == "PROVIDER_REJECTED"


@pytest.mark.asyncio
async def test_finalize_requires_real_artifact_qc_and_exact_credit_delta(monkeypatch):
    profile = _profile()
    row = {
        "certification_id": "pec_test",
        "status": "SUBMITTED",
        "job_id": "g_test",
        "profile_json": service._stable_json(profile),
    }
    lineage = {"provider_scene_artifact": {"sha256": "scene-sha"}}
    job = {
        "job_id": "g_test",
        "status": "DONE",
        "provider_operation_ids": ["operations/one"],
        "media_id": "exact-media",
        "artifacts": [{"media_id": "exact-media", "exact_product_lineage": lineage}],
        "artifact_file_evidence": {
            "exact-media": {"sha256": "output-sha", "size_bytes": 10}
        },
        "credit_accounting": {"delta": 10},
    }
    qc = {"status": "PASS", "artifact_sha256": "output-sha"}
    qc.update({key: True for key in service._FRAME_QC_FIELDS})
    monkeypatch.setattr(service._crud, "get_by_id", lambda _id: _async(row))
    updated = dict(row, status="CERTIFIED", output_sha256="output-sha")
    monkeypatch.setattr(
        service._crud,
        "update_certification",
        lambda _id, **values: _async({**updated, **values}),
    )
    result = await service.finalize_capture("pec_test", job=job, frame_qc=qc)
    assert result["status"] == "CERTIFIED"
    assert result["provider_operation_id"] == "operations/one"
    assert result["source_sha256"] == "scene-sha"


@pytest.mark.asyncio
async def test_finalize_accepts_promo_credit_delta_below_profile_ceiling(monkeypatch):
    profile = _profile()
    row = {
        "certification_id": "pec_promo",
        "status": "SUBMITTED",
        "job_id": "g_promo",
        "profile_json": service._stable_json(profile),
    }
    lineage = {
        "provider_scene_artifact": {
            "sha256": "scene-sha",
            "provider_operation_id": "media-generation/one",
        }
    }
    job = {
        "job_id": "g_promo",
        "status": "DONE",
        "media_id": "exact-media",
        "artifacts": [{
            "media_id": "exact-media",
            "exact_product_lineage": lineage,
            "output_sha256": "output-sha",
        }],
        "artifact_file_evidence": {
            "exact-media": {"sha256": "output-sha", "size_bytes": 10}
        },
        "credit_accounting": {"delta": 8},
    }
    qc = {"status": "PASS", "artifact_sha256": "output-sha"}
    qc.update({key: True for key in service._FRAME_QC_FIELDS})
    monkeypatch.setattr(service._crud, "get_by_id", lambda _id: _async(row))
    monkeypatch.setattr(
        service._crud,
        "update_certification",
        lambda _id, **values: _async({**row, **values}),
    )
    result = await service.finalize_capture("pec_promo", job=job, frame_qc=qc)
    assert result["status"] == "CERTIFIED"
    assert result["provider_operation_id"] == "media-generation/one"
    assert result["credit_delta"] == 8


async def _async(value):
    return value
