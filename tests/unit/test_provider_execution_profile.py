"""Provider-free shared provider-profile governance tests."""

from __future__ import annotations

import pytest

from agent.services import execution_approval_service as eas
from agent.services import make_video
from agent.services.provider_execution_profile import (
    ERR_PROFILE_BLOCK_COUNT_MISMATCH,
    ProviderExecutionProfileError,
    PROFILE_CERTIFIED,
    PROFILE_NOT_CERTIFIED,
    resolve_lane_execution,
    resolve_provider_execution_profile,
)
from agent.services.video_surface_provenance import normalize_surface_lane


def _profile_request(**overrides):
    request = {
        "provider": "GOOGLE_FLOW",
        "model": "veo_3_1_lite",
        "duration_seconds": 8,
        "prompt_block_count": 1,
        "aspect_ratio": "9:16",
        "output_count": 1,
        "reference_topology": "ONE_REFERENCE",
        "generation_type": "reference_frame_2_video",
        "execution_transport": "google_flow_reference",
        "provider_model_key": "veo_3_1_r2v_lite",
        "capability_contract_version": "veo-8s-reference-v1",
    }
    request.update(overrides)
    return request


def _omni_10(**overrides):
    request = {
        "provider": "GOOGLE_FLOW",
        "model": "omni_flash",
        "duration_seconds": 10,
        "prompt_block_count": 1,
        "aspect_ratio": "9:16",
        "output_count": 1,
        "reference_topology": "ONE_REFERENCE",
        "generation_type": "reference_frame_2_video",
        "execution_transport": "flow_creation_agent",
        "provider_model_key": "abra_r2v_10s",
        "capability_contract_version": "flow-agent-reference-omni10-v1",
        "provider_tool": "generate_video_with_references",
        "provider_rpc": "agent_stream_chat",
    }
    request.update(overrides)
    return request


def _native_extend(duration: int, **overrides):
    request = {
        "provider": "GOOGLE_FLOW",
        "model": "veo_3_1_lite",
        "duration_seconds": duration,
        "aspect_ratio": "9:16",
        "output_count": 1,
        "reference_topology": "SOURCE_AGNOSTIC",
        "generation_type": "native_extend",
        "execution_transport": "google_flow_native_extend",
        "provider_model_key": "veo_3_1_extension_lite",
        "capability_contract_version": "google-flow-native-extend-v1",
    }
    request.update(overrides)
    return request


def test_identical_8s_profile_hybrid_and_montage_share_id():
    hybrid = resolve_provider_execution_profile(
        _profile_request(surface_lane="HYBRID")
    )
    montage = resolve_provider_execution_profile(
        _profile_request(surface_lane="MONTAGE")
    )
    assert hybrid["profile_id"] == montage["profile_id"]
    assert hybrid["provider_profile_digest"] == montage["provider_profile_digest"]


def test_identical_8s_profile_faceless_and_p6_share_id():
    faceless = resolve_provider_execution_profile(
        _profile_request(surface_lane="FACELESS", copy_digest="copy-a")
    )
    p6 = resolve_provider_execution_profile(
        _profile_request(surface_lane="PRODUCTION_STUDIO_P6", manifest_digest="m-a")
    )
    assert faceless["profile_id"] == p6["profile_id"]


def test_exact_10s_omni_reference_certification_is_shared_across_active_surfaces():
    profiles = [
        resolve_provider_execution_profile(_omni_10(surface_lane=surface))
        for surface in ("HYBRID", "FACELESS", "MONTAGE", "PRODUCTION_STUDIO_P6")
    ]
    assert {item["profile_id"] for item in profiles}.__len__() == 1
    assert {item["certification_status"] for item in profiles} == {PROFILE_CERTIFIED}


def test_surface_and_lane_owned_fields_are_excluded_from_certification_identity():
    base = resolve_provider_execution_profile(_omni_10(surface_lane="HYBRID"))
    changed_adapter = resolve_provider_execution_profile(
        _omni_10(
            surface_lane="MONTAGE",
            copy_digest="different",
            custody_digest="different",
            staff_id="staff-2",
            package_id="package-2",
            scene_count=2,
        )
    )
    assert base["profile_id"] == changed_adapter["profile_id"]
    assert "surface_lane" not in base["identity"]


def test_model_duration_and_reference_topology_changes_change_profile_id():
    base = resolve_provider_execution_profile(_omni_10())
    changed_model = resolve_provider_execution_profile(
        _omni_10(model="veo_3_1_fast", provider_model_key="veo_3_1_r2v_fast")
    )
    changed_duration = resolve_provider_execution_profile(
        _omni_10(
            duration_seconds=8,
            provider_model_key="veo_3_1_r2v_lite",
            capability_contract_version="veo-8s-reference-v1",
            provider_tool=None,
            provider_rpc=None,
        )
    )
    changed_topology = resolve_provider_execution_profile(
        _omni_10(reference_topology="TWO_REFERENCES", output_count=1)
    )
    assert base["profile_id"] != changed_model["profile_id"]
    assert base["profile_id"] != changed_duration["profile_id"]
    assert base["profile_id"] != changed_topology["profile_id"]


def test_8s_does_not_unlock_10s_16s_or_24s():
    eight = resolve_provider_execution_profile(_profile_request())
    ten = resolve_provider_execution_profile(_omni_10())
    sixteen = resolve_provider_execution_profile(_native_extend(16))
    twenty_four = resolve_provider_execution_profile(_native_extend(24))
    assert eight["certification_status"] == PROFILE_NOT_CERTIFIED
    assert eight["profile_id"] not in {
        ten["profile_id"], sixteen["profile_id"], twenty_four["profile_id"]
    }
    assert eight["duration_seconds"] == 8


def test_16s_and_24s_have_exact_native_extend_block_counts():
    sixteen = resolve_provider_execution_profile(_native_extend(16))
    twenty_four = resolve_provider_execution_profile(_native_extend(24))
    assert sixteen["prompt_block_count"] == sixteen["block_count"] == 2
    assert twenty_four["prompt_block_count"] == twenty_four["block_count"] == 3
    with pytest.raises(ProviderExecutionProfileError) as sixteen_error:
        resolve_provider_execution_profile(_native_extend(16, prompt_block_count=3))
    assert sixteen_error.value.code == ERR_PROFILE_BLOCK_COUNT_MISMATCH
    with pytest.raises(ProviderExecutionProfileError) as twenty_four_error:
        resolve_provider_execution_profile(_native_extend(24, prompt_block_count=2))
    assert twenty_four_error.value.code == ERR_PROFILE_BLOCK_COUNT_MISMATCH


def test_certified_profile_does_not_bypass_lane_validation():
    with pytest.raises(ProviderExecutionProfileError) as exc:
        resolve_lane_execution(
            "MONTAGE", _omni_10(), lane_validator=lambda _lane, _request: False
        )
    assert exc.value.code == "LANE_VALIDATION_FAILED"


def test_internal_transport_vocabulary_is_not_a_public_surface():
    for value in ("T2V", "F2V", "I2V"):
        with pytest.raises(ValueError):
            normalize_surface_lane(value)


def test_approval_keeps_provider_digest_separate_from_lane_envelope_digest():
    profile = resolve_provider_execution_profile(_omni_10())
    identity = eas.compute_dispatch_identity(
        mode="F2V",
        final_prompt_text="provider profile approval proof",
        source_mode="HYBRID",
        model="omni_flash",
        aspect="9:16",
        duration_s=10,
        count=1,
        asset_media_ids=["reference-1"],
        provider_profile=profile,
    )
    assert identity["provider_profile_digest"] == profile["provider_profile_digest"]
    assert identity["provider_profile_digest"] != identity["execution_envelope_sha256"]
    assert (
        identity["execution_envelope"]["provider_profile_digest"]
        == profile["provider_profile_digest"]
    )


def test_pr_884_montage_execution_identity_route_remains_green():
    plan = make_video._direct_lane_plan(
        "F2V", "HYBRID", "omni_flash", 10, "9:16",
        ref_count=1, num_videos=1, require_flag=False, surface_lane="MONTAGE",
    )
    assert plan["execution_route"] == make_video.HYBRID_REFERENCE_OMNI_10S_CERTIFIED_ROUTE
    assert plan["provider_profile_status"] == PROFILE_CERTIFIED
