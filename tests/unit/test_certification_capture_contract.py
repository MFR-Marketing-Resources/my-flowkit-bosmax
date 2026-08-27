"""``validate_capture_contract`` surface/recipe/lane agreement.

The certification profile is lane-INDEPENDENT, so a bounded capture may certify
it from either the FACELESS or the exact-product HYBRID surface (owner directive:
bind the actual HYBRID identity, do not certify HYBRID as FACELESS).  Surface,
production recipe, and the resolved profile lane must all agree.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.services import provider_certification_service as service
from agent.services import video_execution_profile_service as profiles


def _valid_profile():
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


def _owner():
    return SimpleNamespace(
        role_codes=("OWNER",), permission_codes=("production.execute",)
    )


def _contract_kwargs(**over):
    kw = dict(
        profile_context={},
        mode="T2V",
        source_mode="T2V",
        model="veo_3_1_lite",
        duration_s=8,
        aspect="9:16",
        num_videos=1,
        image_media_ids=[],
        product_id="p1",
        production_recipe="HYBRID",
        surface_lane="HYBRID",
        product_visual_custody={
            "provider_route": "EXACT_PRODUCT_DETERMINISTIC_COMPOSITE",
            "provider_product_reference_forbidden": True,
        },
        confirm_live_credit_burn=True,
        maximum_provider_operations=1,
        max_retry_operations=0,
        auth_context=_owner(),
    )
    kw.update(over)
    return kw


@pytest.mark.parametrize("lane", ["HYBRID", "FACELESS"])
def test_accepts_hybrid_and_faceless(monkeypatch, lane):
    prof = _valid_profile()
    monkeypatch.setattr(
        service._profiles,
        "normalize_approval_context",
        lambda _ctx: {"duration_model_profile": prof, "lane": lane},
    )
    out = service.validate_capture_contract(
        **_contract_kwargs(surface_lane=lane, production_recipe=lane)
    )
    assert out["lane"] == lane


def test_rejects_recipe_surface_mismatch(monkeypatch):
    prof = _valid_profile()
    monkeypatch.setattr(
        service._profiles,
        "normalize_approval_context",
        lambda _ctx: {"duration_model_profile": prof, "lane": "HYBRID"},
    )
    with pytest.raises(service.ProviderCertificationError) as exc:
        service.validate_capture_contract(
            **_contract_kwargs(surface_lane="HYBRID", production_recipe="FACELESS")
        )
    assert exc.value.code == "PROFILE_CERTIFICATION_RECIPE_MUST_MATCH_SURFACE"


def test_rejects_non_certifiable_surface():
    # reached before any profile-context resolution
    with pytest.raises(service.ProviderCertificationError) as exc:
        service.validate_capture_contract(
            **_contract_kwargs(surface_lane="MONTAGE", production_recipe="MONTAGE")
        )
    assert exc.value.code == "PROFILE_CERTIFICATION_SURFACE_NOT_CERTIFIABLE"


def test_rejects_profile_lane_surface_mismatch(monkeypatch):
    prof = _valid_profile()
    # resolved profile lane disagrees with the requested surface
    monkeypatch.setattr(
        service._profiles,
        "normalize_approval_context",
        lambda _ctx: {"duration_model_profile": prof, "lane": "FACELESS"},
    )
    with pytest.raises(service.ProviderCertificationError) as exc:
        service.validate_capture_contract(
            **_contract_kwargs(surface_lane="HYBRID", production_recipe="HYBRID")
        )
    assert exc.value.code == "PROFILE_CERTIFICATION_PROFILE_LANE_MUST_MATCH_SURFACE"
