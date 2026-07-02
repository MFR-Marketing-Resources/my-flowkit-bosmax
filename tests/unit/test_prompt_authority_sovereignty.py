"""Sovereignty proofs (ADR-008 repair wave 2): no competing final-prompt
authority can silently reassert; source modes and workbook planning are
reachable end-to-end; the avatar bridge is fail-closed."""
import asyncio

import pytest

from agent.services import avatar_registry
from agent.services import prompt_compiler_9_section as shim
from agent.services.prompt_compiler_runtime_config_service import LANGUAGE_WPS_POLICY
from agent.services.ugc_video_prompt_compiler_service import compile_ugc_video_prompt

PRODUCT = {"id": "prod-x", "name": "Produk Uji", "category": "Beauty & Personal Care"}


def _run(coro):
    return asyncio.run(coro)


def test_legacy_9_section_shim_renders_canonical(monkeypatch):
    # batch_planner + creative_brief call this signature; it must now emit the
    # CANONICAL taxonomy, not "Biometric Anchor DNA".
    async def fake_brief(product_id):
        return {
            "product_intelligence": {"product_short_name": "Produk Uji",
                                     "category": "Beauty & Personal Care"},
            "copywriting_route": {"copywriting_angle": "routine_upgrade", "formula": "HSO"},
            "physics_dna": {"section_5_product_physics_prompt": ""},
        }

    monkeypatch.setattr(shim, "get_creative_brief", fake_brief)
    prompt = _run(shim.compile_9_section_prompt("prod-x", {
        "scene_context": "bright vanity table", "hook_angle": "product reveal",
        "camera_route": "static close shot", "duration_seconds": 8,
    }))
    assert prompt.startswith("SECTION 1 - ROLE & OBJECTIVE")
    assert "SECTION 9 - NO_OVERLAY" in prompt
    assert "Biometric Anchor" not in prompt
    assert "Dialogue & Silo Purity" not in prompt
    assert "The presenter is a Malaysian adult" in prompt


def test_requested_total_duration_derives_workbook_chain():
    # Operator asks 24s total → workbook says Google Flow 24s = [8,8,8].
    result = compile_ugc_video_prompt(
        product=PRODUCT, approved_package={}, mode="F2V",
        target_language="BM_MS", generation_mode="SINGLE", duration_seconds=8,
        requested_total_duration_seconds=24,
    )
    assert len(result["prompt_blocks"]) == 3
    assert [b["duration_seconds"] for b in result["prompt_blocks"]] == [8, 8, 8]


def test_requested_total_40s_fails_closed_without_lane():
    with pytest.raises(ValueError, match="PREFERRED_LANE_REQUIRED"):
        compile_ugc_video_prompt(
            product=PRODUCT, approved_package={}, mode="F2V",
            target_language="BM_MS", generation_mode="SINGLE", duration_seconds=8,
            requested_total_duration_seconds=40,
        )


def test_explicit_source_mode_frames_reaches_renderer():
    result = compile_ugc_video_prompt(
        product=PRODUCT, approved_package={}, mode="F2V",
        target_language="BM_MS", generation_mode="SINGLE", duration_seconds=8,
        source_mode="FRAMES",
    )
    text = result["final_compiled_prompt_text"]
    assert "uploaded finished frame" in text
    assert "The presenter is a Malaysian adult" not in text  # frame is the identity truth


def test_ui_wps_policy_mirrors_workbook_authority():
    # The operator UI reads LANGUAGE_WPS_POLICY; it must mirror the workbook
    # (Malay Safe 2.4 / Sweet 2.7), never the legacy 1.7 estimate.
    bm = LANGUAGE_WPS_POLICY["BM_MS"]
    assert bm["body_wps"] == 2.4 and bm["safe_wps"] == 2.4
    assert bm["sweet_wps"] == 2.7
    en = LANGUAGE_WPS_POLICY["EN_US"]
    assert en["safe_wps"] == 2.3 and en["sweet_wps"] == 2.45


def test_avatar_bridge_sync_fail_closed_and_reload(tmp_path, monkeypatch):
    bridge = tmp_path / "AVATAR_POOL_NORMALIZED.csv"
    monkeypatch.setattr(avatar_registry, "_BRIDGE_FILE", bridge)
    avatar_registry.reload_pool()
    # invalid: missing columns
    with pytest.raises(ValueError, match="AVATAR_REGISTRY_COLUMNS_MISSING"):
        avatar_registry.sync_pool_csv(b"AvatarCode\nBOS_F_X_01\n")
    # invalid: duplicate codes
    dup = ("CharacterName,AvatarCode,SkinTone,HairStyle,Wardrobe,Expression\n"
           "A,BOS_F_A_01,Light,Neat,Casual,Calm\nB,BOS_F_A_01,Light,Neat,Casual,Calm\n")
    with pytest.raises(ValueError, match="DUPLICATE_AVATAR_CODE"):
        avatar_registry.sync_pool_csv(dup.encode())
    # valid sync: overrides the repo seed and resolves from the bridge
    good = ("CharacterName,AvatarCode,SkinTone,HairStyle,Wardrobe,Expression\n"
            "Zara,BOS_F_ZARA_99,Medium,Long wavy,Modern baju kurung,Warm smile\n")
    info = avatar_registry.sync_pool_csv(good.encode())
    assert info["approved_loaded"] == 1
    profile = avatar_registry.resolve_presenter("BOS_F_ZARA_99")
    assert profile["character_name"] == "Zara"
    # restore the repo seed for other tests
    bridge.unlink()
    avatar_registry.reload_pool()


def test_generation_package_compile_call_is_wired_correctly():
    # The generation-package lane previously awaited a sync function with a
    # nonexistent product_id kwarg (TypeError on every call). Lock the repair:
    import inspect
    from agent.services import workspace_generation_package_service as wgps
    src = inspect.getsource(wgps)
    assert "await compile_ugc_video_prompt" not in src
    assert "product_id=product_id,\n        mode=mode" not in src
    assert "[I2V Semantic Context]" not in src  # no post-compile mutation

def test_explicit_source_mode_hybrid_first_class():
    # The /operator/hybrid surface sends job mode F2V + source_mode HYBRID:
    # product-image anchor + ONE concrete registry presenter, end-to-end.
    result = compile_ugc_video_prompt(
        product=PRODUCT, approved_package={}, mode="F2V",
        target_language="BM_MS", generation_mode="SINGLE", duration_seconds=8,
        source_mode="HYBRID",
    )
    text = result["final_compiled_prompt_text"]
    assert "uploaded product image" in text
    assert "The presenter is a Malaysian adult" in text
    assert "one visible creator" not in text.lower()


def test_generation_package_request_models_default_no_overlay():
    # Residual gap from the Codex counter era: the pydantic request models in
    # agent/models/workspace_generation_package.py still defaulted True.
    import inspect
    from agent.models import workspace_generation_package as m
    for _name, cls in inspect.getmembers(m, inspect.isclass):
        if hasattr(cls, "model_fields") and "overlay_enabled" in getattr(cls, "model_fields", {}):
            default = cls.model_fields["overlay_enabled"].default
            assert default is False, f"{cls.__name__}.overlay_enabled must default False (NO_OVERLAY law)"

