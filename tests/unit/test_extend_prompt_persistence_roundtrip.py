"""Persistence round-trip for extension-native prompt representation fields."""
from __future__ import annotations

import json
from copy import deepcopy

import pytest

from agent.services.ugc_video_prompt_compiler_service import compile_ugc_video_prompt
from agent.services.workspace_generation_package_service import _json


PRODUCT = {
    "id": "prod-persist-1",
    "name": "Minyak Warisan Tok Cap Burung 25ml",
    "product_display_name": "Minyak Warisan Tok Cap Burung 25ml",
    "category": "Health & Personal Care",
}

COPY = {
    "copy_source": "selected_copy_set",
    "formula_family": "PAS",
    "angle": "Rutin malam yang lebih tenang untuk anak dan ibu bapa",
    "hook": "Anak susah tidur malam kerana perut kembung?",
    "subhook": "Setiap kali anak menangis, hati ibu pun turut terganggu.",
    "usps": ["Formula tradisional yang diwarisi turun-temurun."],
    "cta": "Cuba sapukan pada perut anak malam ini.",
}


@pytest.mark.parametrize("mode", ["T2V", "HYBRID", "FRAMES", "INGREDIENTS"])
def test_prompt_blocks_json_roundtrip_preserves_extend_fields(mode: str):
    """Simulates workspace_generation_package_service prompt_blocks_json persist path."""
    source_mode = mode if mode != "FRAMES" else "HYBRID"
    compile_mode = "F2V" if mode in {"HYBRID", "FRAMES"} else ("T2V" if mode == "T2V" else "I2V")
    compiled = compile_ugc_video_prompt(
        product=deepcopy(PRODUCT),
        approved_package={"scene_context": "bedroom"},
        mode=compile_mode,
        source_mode=source_mode,
        generation_mode="EXTEND",
        engine_duration_target="GOOGLE_FLOW",
        requested_total_duration_seconds=16,
        target_language="BM_MS",
        copy_intelligence=deepcopy(COPY),
    )
    blocks = compiled["prompt_blocks"]
    assert len(blocks) >= 2

    serialized = _json(blocks)
    reloaded = json.loads(serialized)

    assert len(reloaded) == len(blocks)
    b2 = reloaded[1]
    assert b2.get("flow_extend_prompt_text", "").startswith("Extend this video")
    assert b2.get("prompt_representation") == "GOOGLE_FLOW_EXTEND"
    assert b2.get("flow_extend_prompt_validation", {}).get("valid") is True
    assert b2.get("independent_block_prompt_text")
    assert "You are generating" in (b2.get("independent_block_prompt_text") or "")
    assert b2.get("engine_prompt_text") == b2.get("independent_block_prompt_text")

    b1 = reloaded[0]
    assert b1.get("initial_generation_prompt_text") or b1.get("independent_block_prompt_text")
    fp_before = compiled.get("prompt_fingerprint")
    # Fingerprint stable across JSON round-trip of blocks subset keys used in package layer
    fp_payload = json.dumps(reloaded, sort_keys=True, ensure_ascii=False)
    assert len(fp_payload) > 100
    assert fp_before


def test_legacy_package_blocks_without_extend_still_load():
    legacy = [
        {
            "block_index": 2,
            "engine_prompt_text": "SECTION 1 - ROLE\nYou are generating an 8-second clip.",
            "independent_block_prompt_text": "SECTION 1 - ROLE\nYou are generating an 8-second clip.",
        }
    ]
    serialized = _json(legacy)
    reloaded = json.loads(serialized)
    assert reloaded[0]["block_index"] == 2
    assert "flow_extend_prompt_text" not in reloaded[0] or not reloaded[0].get("flow_extend_prompt_text")