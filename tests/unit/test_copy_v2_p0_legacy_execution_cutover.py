"""P0 proof: V2-bound execution never crosses the legacy safe-copy seam.

These tests use only synthetic product/resolution fixtures.  They do not call a
provider, approve a blueprint, activate a lane, or use the canonical runtime
database for authoring.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent.models.copy_blueprint_v2 import CopyBlueprintV2FeatureFlagState
from agent.services import approved_product_package_service as approved_packages
from agent.services import creative_production_compile_service as p6_compile
from agent.services import workspace_execution_package_service as execution_packages
from agent.services.copy_execution_resolver import CopyExecutionResolution


PRODUCT_ID = "p0-v2-synthetic-product"
APPROVED_DIALOGUE = "Hook V2. Body V2. CTA V2."
COMPILER_COPY = {
    "copy_source": "copy_blueprint_v2",
    "formula_id": "PAS",
    "formula_version": "copy-formula-registry-v1:test",
    "blueprint_id": "bpv2-synthetic",
    "revision": 1,
    "hook": "Hook V2.",
    "usps": ["Body V2."],
    "cta": "CTA V2.",
}


def _resolution(lane: str) -> CopyExecutionResolution:
    flags = CopyBlueprintV2FeatureFlagState(
        enabled=True,
        shadow_mode=False,
        scope="global",
        pilot_scope=(),
        state="ON",
    )
    return CopyExecutionResolution(
        lane=lane,
        media_kind="VIDEO",
        copy_policy="REQUIRED",
        feature_flags=flags,
        v2_enabled=True,
        status="READY",
        compiler_copy_intelligence=dict(COMPILER_COPY),
        approved_dialogue=APPROVED_DIALOGUE,
        metadata={"authority_fingerprint": "authority-v2-synthetic"},
    )


def _product() -> dict:
    return {
        "id": PRODUCT_ID,
        "product_display_name": "Synthetic V2 Product",
        "raw_product_title": "Synthetic V2 Product",
        "image_url": None,
        # Deliberately stale and malformed legacy data.  It is not an input to
        # any V2 package or compiler assertion below.
        "claim_safe_copy_payload": json.dumps(
            {"safe_hook_angles": ["STALE_LEGACY_HOOK"], "garbage": True}
        ),
        "scene_context": "A clean product-first room.",
        "category": "Health & Personal Care",
        "subcategory": "Traditional Wellness",
        "type": "Traditional Herbal Oils",
        "product_type": "TRADITIONAL_HERBAL_OIL",
        "product_type_id": "BEAUTY_PERSONAL_CARE",
        "silo": "baby_care_universal_01",
        "bosmax_product_family": "BEAUTY_PERSONAL_CARE",
    }


def _compiler_result() -> dict:
    return {
        "final_compiled_prompt_text": "Synthetic deterministic prompt.",
        "prompt_blocks": [],
        "compiler_version": "synthetic-test-compiler",
        "source_mode": "T2V",
        "generation_mode": "SINGLE",
        "total_duration_seconds": 8,
        "camera_style": "UGC_IPHONE_RAW",
        "character_presence": "FACELESS",
        "creator_persona": "DEFAULT_CREATOR",
        "target_language": "BM_MS",
        "shot_plan": [],
        "dialogue_word_budget_per_block": [],
        "prompt_fingerprint": "synthetic-prompt-fingerprint",
        "warnings": [],
        "blockers": [],
        "source_of_truth_notes": [],
        "continuation_lineage": [],
        "runtime_config_snapshot": {},
    }


@pytest.mark.asyncio
async def test_v2_package_projection_ignores_stale_legacy_payload(monkeypatch):
    product = _product()

    async def fake_product(product_id):
        assert product_id == PRODUCT_ID
        return dict(product)

    async def fake_enrich(row, *, persist=False):
        assert persist is False
        return {**row, "lifecycle_status": "ACTIVE", "image_readiness_status": "IMAGE_NOT_AVAILABLE"}

    async def eligible(product_id):
        assert product_id == PRODUCT_ID
        return {"product_id": product_id, "eligible": True, "reasons": []}

    async def forbidden_legacy_getter(_product_id):
        raise AssertionError("V2 package reached get_stored_claim_safe_package")

    monkeypatch.setattr(approved_packages.crud, "get_product", fake_product)
    monkeypatch.setattr(approved_packages, "enrich_product", fake_enrich)
    monkeypatch.setattr(
        "agent.services.copy_eligibility_service.assert_copy_eligible", eligible
    )
    monkeypatch.setattr(
        approved_packages, "get_stored_claim_safe_package", forbidden_legacy_getter
    )
    monkeypatch.setattr(approved_packages, "_asset_slots_for_mode", lambda *_: ([], []))

    package = await approved_packages.get_v2_approved_product_package(
        PRODUCT_ID,
        "T2V",
        copy_v2_resolution=_resolution("T2V"),
    )

    assert package["approved_dialogue"] == APPROVED_DIALOGUE
    assert package["copy_intelligence"] == COMPILER_COPY
    assert package["claim_safe_rewrite"] == ""
    assert "STALE_LEGACY_HOOK" not in json.dumps(package)
    assert "product.claim_safe_copy_payload" in " ".join(package["source_of_truth_notes"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lane", "transport_mode", "source_mode"),
    [
        ("T2V", "T2V", None),
        ("F2V", "F2V", "FRAMES"),
        ("HYBRID", "F2V", "HYBRID"),
        ("I2V", "I2V", None),
        ("FACELESS", "F2V", "HYBRID"),
        ("MONTAGE", "F2V", "HYBRID"),
        ("PRODUCTION_STUDIO_P6", "F2V", "HYBRID"),
    ],
)
async def test_every_required_video_lane_uses_only_v2_copy(
    monkeypatch,
    lane,
    transport_mode,
    source_mode,
):
    product = _product()
    resolution = _resolution(lane)
    captured: dict = {}

    async def fake_product(product_id):
        assert product_id == PRODUCT_ID
        return dict(product)

    async def fake_enrich(row, *, persist=False):
        return {**row, "lifecycle_status": "ACTIVE", "image_readiness_status": "IMAGE_NOT_AVAILABLE"}

    async def eligible(_product_id):
        return {"eligible": True, "reasons": []}

    async def forbidden_legacy_getter(_product_id):
        raise AssertionError("V2 lane reached get_stored_claim_safe_package")

    async def forbidden_legacy_copy_resolver(*_args, **_kwargs):
        raise AssertionError("V2 lane reached the legacy CopySet resolver")

    def fake_compile(**kwargs):
        captured.update(kwargs)
        return _compiler_result()

    monkeypatch.setattr(execution_packages.crud, "get_product", fake_product)
    monkeypatch.setattr(execution_packages, "enrich_product", fake_enrich)
    monkeypatch.setattr(approved_packages, "enrich_product", fake_enrich)
    monkeypatch.setattr(
        "agent.services.copy_eligibility_service.assert_copy_eligible", eligible
    )
    monkeypatch.setattr(
        approved_packages, "_asset_slots_for_mode", lambda *_: ([], [])
    )
    monkeypatch.setattr(
        approved_packages, "get_stored_claim_safe_package", forbidden_legacy_getter
    )
    monkeypatch.setattr(
        execution_packages, "get_stored_claim_safe_package", forbidden_legacy_getter
    )
    monkeypatch.setattr(
        execution_packages,
        "resolve_compiler_copy_intelligence",
        forbidden_legacy_copy_resolver,
    )
    monkeypatch.setattr(
        execution_packages, "compile_ugc_video_prompt", fake_compile
    )
    monkeypatch.setattr(
        execution_packages, "scan_prompt_text", lambda *_args, **_kwargs: {}
    )

    result = await execution_packages.compile_workspace_prompt_preview(
        product_id=PRODUCT_ID,
        mode=transport_mode,
        duration_seconds=8,
        source_mode=source_mode,
        character_presence="FACELESS",
        copy_v2_resolution=resolution,
    )

    assert captured["copy_intelligence"] == COMPILER_COPY
    assert captured["approved_dialogue"] == APPROVED_DIALOGUE
    assert captured["claim_safe_rewrite"] == ""
    assert captured["safe_hook_angles"] == []
    assert captured["safe_cta_angles"] == []
    assert result["copy_binding"]["lane"] == lane
    assert result["copy_binding"]["v2_enabled"] is True


@pytest.mark.asyncio
async def test_v2_package_fails_closed_without_ready_binding(monkeypatch):
    class NotReady:
        v2_enabled = True
        ready = False

    with pytest.raises(ValueError, match="COPY_V2_EXECUTION_NOT_READY"):
        await approved_packages.get_v2_approved_product_package(
            PRODUCT_ID,
            "T2V",
            copy_v2_resolution=NotReady(),
        )


@pytest.mark.asyncio
async def test_poster_builder_v2_projection_never_reads_legacy_poster_copy(
    monkeypatch,
):
    class FakeResolution:
        v2_enabled = True
        projection = SimpleNamespace(
            derived_copy=SimpleNamespace(
                hook="Poster V2 hook.",
                body="Poster V2 body.",
                cta="Poster V2 CTA.",
            )
        )
        binding = None

        def to_metadata(self, **_kwargs):
            return {"lane": "POSTER_BUILDER", "v2_enabled": True}

    captured = {}

    async def fake_resolve(*_args, **_kwargs):
        return FakeResolution()

    async def fake_build(request):
        captured.update(request.model_dump(mode="json"))
        return SimpleNamespace(
            model_dump=lambda mode="json": {
                "status": "DRAFT_READY",
                "final_prompt": "Synthetic poster prompt.",
                "blockers": [],
            }
        )

    async def forbidden_legacy_poster_read(*_args, **_kwargs):
        raise AssertionError("V2 poster path reached legacy poster copy storage")

    monkeypatch.setattr(p6_compile, "resolve_persisted_copy_execution_binding", fake_resolve)
    monkeypatch.setattr(p6_compile, "legacy_copy_maintenance_enabled", lambda: False)
    monkeypatch.setattr(p6_compile.PosterPromptDraftService, "build_draft", fake_build)
    monkeypatch.setattr(p6_compile.p6db, "get_poster_copy_set", forbidden_legacy_poster_read, raising=False)

    _item = {
        "product_id": PRODUCT_ID,
        "item_id": "p6-item-1",
        "creative_dna_sha256": "synthetic-dna",
    }
    _plan = {
        "pool_snapshot_json": json.dumps(
            {"copy_v2_context": {"lane": "POSTER_BUILDER"}}
        )
    }
    _dimensions = {
        "marketing_angle": "V2 poster objective",
        "layout_id": "poster-recipe-v2",
    }

    _item_id, _fingerprint, result = await p6_compile._compile_poster(
        _item,
        _plan,
        _dimensions,
    )

    assert _item_id is None
    assert captured["copy_source"] == "COPY_BLUEPRINT_V2_APPROVED"
    assert captured["poster_copy_set_id"] == ""
    assert result["copy_architecture_v2"]["lane"] == "POSTER_BUILDER"
