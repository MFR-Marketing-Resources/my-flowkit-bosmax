"""Focused contracts for shared duration/model provider certification."""

from __future__ import annotations

import pytest

from agent.services import execution_approval_service as eas
from agent.services import video_execution_profile_service as profiles


def _profile(duration: int, *, model: str | None = None) -> dict:
    return profiles.resolve_duration_model_profile(
        model=model or ("omni_flash" if duration == 10 else "veo_3_1_lite"),
        duration_s=duration,
        aspect_ratio="9:16",
        logical_mode="F2V",
        source_mode="HYBRID",
    )


def _certified_registry(profile: dict) -> dict:
    return {
        profile["profile_digest"]: {
            "profile_digest": profile["profile_digest"],
            "status": "CERTIFIED",
            "proof_id": f"fixture:{profile['duration_s']}s",
        }
    }


@pytest.mark.parametrize(
    ("duration", "blocks"),
    [(8, [8]), (10, [10]), (16, [8, 8]), (24, [8, 8, 8])],
)
def test_duration_profile_uses_canonical_prompt_block_plan(duration, blocks):
    profile = _profile(duration)
    assert profile["prompt_block_durations_s"] == blocks
    assert profile["prompt_block_count"] == len(blocks)
    assert profile["duration_s"] == duration
    assert profile["capability_matrix_version"] == "video-capability-v1"
    assert profile["provider_transport_key_provenance"]
    assert profile["credits_cost_rule"]["currency"] == "Flow credits"
    assert profile["credits_cost_rule"]["unit_cost_ceiling"] > 0


@pytest.mark.parametrize("lane", ["HYBRID", "FACELESS", "MONTAGE", "PRODUCTION_STUDIO_P6"])
def test_one_certified_8s_profile_is_reused_by_eligible_lanes(lane):
    profile = _profile(8)
    registry = _certified_registry(profile)
    result = profiles.evaluate_lane_profile(
        profile,
        lane=lane,
        lane_gate_passed=True,
        registry=registry,
    )
    assert result["eligible"] is True
    assert result["provider_certification"]["certified"] is True


@pytest.mark.parametrize("duration", [8, 10, 16, 24])
def test_one_certified_profile_is_shared_only_with_same_duration(duration):
    profile = _profile(duration)
    registry = _certified_registry(profile)
    assert profiles.provider_certification_status(profile, registry=registry)["certified"]

    for other_duration in {8, 10, 16, 24} - {duration}:
        other = _profile(other_duration)
        result = profiles.provider_certification_status(other, registry=registry)
        assert result["certified"] is False
        assert result["reason"] == "NO_PROVIDER_CERTIFICATION_FOR_PROFILE"


def test_16s_and_24s_require_exact_prompt_block_counts():
    with pytest.raises(profiles.ExecutionProfileError) as sixteen:
        profiles.resolve_duration_model_profile(
            model="veo_3_1_lite", duration_s=16, prompt_block_count=1,
            logical_mode="F2V", source_mode="HYBRID",
        )
    assert sixteen.value.code == "PROMPT_BLOCK_COUNT_MISMATCH"

    with pytest.raises(profiles.ExecutionProfileError) as twenty_four:
        profiles.resolve_duration_model_profile(
            model="veo_3_1_lite", duration_s=24, prompt_block_count=2,
            logical_mode="F2V", source_mode="HYBRID",
        )
    assert twenty_four.value.code == "PROMPT_BLOCK_COUNT_MISMATCH"


def test_lane_specific_gate_stays_separate_from_provider_certification():
    profile = _profile(8)
    result = profiles.evaluate_lane_profile(
        profile,
        lane="MONTAGE",
        lane_gate_passed=False,
        lane_gate_reason="PRODUCT_MASCOT_KEY_VISUAL_REQUIRED",
        registry=_certified_registry(profile),
    )
    assert result["provider_certification"]["certified"] is True
    assert result["eligible"] is False
    assert result["blocker"] == "PRODUCT_MASCOT_KEY_VISUAL_REQUIRED"


def test_source_mode_route_is_derived_and_ambiguous_route_fails_closed():
    assert profiles.derive_transport_route(
        logical_mode="T2V", source_mode="T2V"
    ) == "GOOGLE_FLOW_CREATION_AGENT"
    assert profiles.derive_transport_route(
        logical_mode="F2V", source_mode="HYBRID"
    ) == "GOOGLE_FLOW_REFERENCE_FRAME_2_VIDEO"
    assert profiles.derive_transport_route(
        logical_mode="F2V", source_mode="FRAMES", reference_count=2
    ) == "GOOGLE_FLOW_START_END_FRAME_2_VIDEO"
    with pytest.raises(profiles.ExecutionProfileError) as exc:
        profiles.derive_transport_route(logical_mode="F2V", source_mode=None)
    assert exc.value.code == "TRANSPORT_ROUTE_REQUIRED"


def test_approval_context_requires_current_authority_digests():
    profile = _profile(8)
    context = profiles.build_approval_context(
        profile,
        lane="FACELESS",
        product_digest="product-current",
        copy_digest="copy-current",
        sweetwps_digest_value="sweetwps-current",
        compositor_digest_value="compositor-current",
        compiler_digest_value="compiler-current",
        adapter_digest="faceless-adapter-current",
    )
    normalized = profiles.normalize_approval_context(context)
    assert normalized["duration_model_profile"]["profile_digest"] == profile["profile_digest"]
    assert normalized["sweetwps_digest"] == "sweetwps-current"

    missing = dict(context)
    missing.pop("compositor_digest")
    with pytest.raises(profiles.ExecutionProfileError) as exc:
        profiles.normalize_approval_context(missing)
    assert exc.value.code == "EXECUTION_PROFILE_DIGESTS_REQUIRED"


def test_authority_digests_use_immutable_source_when_runtime_root_is_relocated(
    monkeypatch, tmp_path
):
    """Canonical state storage must not be treated as the source tree.

    The production launcher sets ``FLOW_AGENT_DIR`` to the external mutable
    state root.  Authority digests still have to read the immutable release
    source, otherwise profile certification fails before provider dispatch with
    ``AUTHORITY_SOURCE_MISSING``.
    """

    runtime_root = tmp_path / "runtime-state"
    runtime_root.mkdir()
    monkeypatch.setattr(profiles, "BASE_DIR", runtime_root)

    assert len(profiles.compositor_digest()) == 64
    assert len(profiles.compiler_digest()) == 64
    assert len(profiles.lane_adapter_digest("FACELESS")) == 64


def test_profile_context_is_provider_affecting_and_rejects_stale_profile_digest():
    profile = _profile(8)
    context = profiles.build_approval_context(
        profile,
        lane="FACELESS",
        product_digest="product-current",
        copy_digest="copy-current",
        sweetwps_digest_value="sweetwps-current",
        compositor_digest_value="compositor-current",
        compiler_digest_value="compiler-current",
        adapter_digest="faceless-adapter-current",
    )
    base = eas.compute_dispatch_identity(
        mode="F2V", final_prompt_text="same prompt", source_mode="HYBRID",
        model="veo_3_1_lite", aspect="9:16", duration_s=8, count=1,
        product_id="product-1", execution_profile_context=context,
    )
    changed = dict(context)
    changed["sweetwps_digest"] = "sweetwps-next"
    changed_identity = eas.compute_dispatch_identity(
        mode="F2V", final_prompt_text="same prompt", source_mode="HYBRID",
        model="veo_3_1_lite", aspect="9:16", duration_s=8, count=1,
        product_id="product-1", execution_profile_context=changed,
    )
    assert base["execution_envelope_sha256"] != changed_identity["execution_envelope_sha256"]

    stale = dict(profile)
    stale["duration_s"] = 10
    with pytest.raises(eas.ExecutionApprovalError) as exc:
        eas.compute_dispatch_identity(
            mode="F2V", final_prompt_text="same prompt", source_mode="HYBRID",
            model="veo_3_1_lite", aspect="9:16", duration_s=8, count=1,
            product_id="product-1",
            execution_profile_context={**context, "duration_model_profile": stale},
        )
    assert exc.value.code == "EXECUTION_PROFILE_CONTEXT_INVALID"


def test_certification_registry_has_one_record_for_all_eligible_lanes():
    profile = _profile(8)
    registry = _certified_registry(profile)
    results = [
        profiles.evaluate_lane_profile(
            profile, lane=lane, lane_gate_passed=True, registry=registry
        )
        for lane in ("HYBRID", "FACELESS", "MONTAGE", "PRODUCTION_STUDIO_P6")
    ]
    assert len(registry) == 1
    assert {row["profile_digest"] for row in results} == {profile["profile_digest"]}


def test_historical_10s_reference_proof_is_stored_by_profile_not_surface():
    profile = profiles.resolve_duration_model_profile(
        model="omni_flash",
        duration_s=10,
        aspect_ratio="9:16",
        provider_transport_key_provenance="captured_flow_agent_contract[abra_r2v_10s]",
        transport_route="FLOW_AGENT_REFERENCE_OMNI_10S",
        logical_mode="F2V",
        source_mode="HYBRID",
    )
    result = profiles.provider_certification_status(profile)
    assert result["certified"] is True
    assert result["record"]["proof_id"] == "HYBRID_REFERENCE_OMNI_10S_CONTRACT_CAPTURE"
