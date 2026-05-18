from agent.services.ugc_video_prompt_compiler_service import (
    compile_ugc_video_prompt,
)


def _product():
    return {
        "id": "4d491c01-2c5a-40c0-869e-54c50050d95d",
        "raw_product_title": "[NEW]Glad2Glow Day & Night Body Serum Set 24-HOUR Body",
        "product_display_name": "[NEW]Glad2Glow Day & Night Body Serum Set 24-HOUR Body",
    }


def _approved_package():
    return {
        "mode": "F2V",
        "claim_safe_rewrite": "Frame the serum as a body-care routine for smooth-feeling, fresh-smelling skin with no guaranteed outcomes.",
    }


def test_compiler_generates_single_block_final_prompt():
    result = compile_ugc_video_prompt(
        product=_product(),
        approved_package=_approved_package(),
        mode="F2V",
        generation_mode="SINGLE",
        duration_seconds=8,
        camera_style="UGC_IPHONE_RAW",
        character_presence="VISIBLE_CREATOR",
        creator_persona="DEFAULT_CREATOR",
        target_language="BM_MS",
        safe_hook_angles=["Mulakan dengan creator tunjuk rutin body serum yang nampak natural dan claim-safe."],
        safe_cta_angles=["Akhiri dengan CTA lembut untuk cuba rutin body-care ini."],
    )

    assert result["generation_mode"] == "SINGLE"
    assert result["total_duration_seconds"] == 8
    assert result["camera_style"] == "UGC_IPHONE_RAW"
    assert result["character_presence"] == "VISIBLE_CREATOR"
    assert result["target_language"] == "BM_MS"
    assert len(result["prompt_blocks"]) == 1
    assert result["prompt_blocks"][0]["shot_count"] == 2
    assert "visible creator" in result["final_compiled_prompt_text"].lower()
    assert "vertical 9:16 handheld iPhone raw style" in result["final_compiled_prompt_text"]
    assert "Claim-safe copy anchor" in result["final_compiled_prompt_text"]
    assert "Shot 1:" in result["final_compiled_prompt_text"]
    assert "Shot 2:" in result["final_compiled_prompt_text"]
    assert "Create a premium frames-to-video sequence" not in result["final_compiled_prompt_text"]


def test_compiler_generates_extend_continuation_lineage():
    result = compile_ugc_video_prompt(
        product=_product(),
        approved_package=_approved_package(),
        mode="F2V",
        generation_mode="EXTEND",
        duration_seconds=8,
        blocks=[
            {"block_index": 1, "duration_seconds": 10},
            {"block_index": 2, "duration_seconds": 6},
        ],
        camera_style="CINEMATIC_PRO",
        character_presence="VISIBLE_CREATOR",
        creator_persona="DEFAULT_CREATOR",
        target_language="EN_US",
        safe_hook_angles=["Open with a creator-led body serum moment that feels native and safe."],
        safe_cta_angles=["Close with a calm CTA to try the routine."],
    )

    assert result["generation_mode"] == "EXTEND"
    assert result["total_duration_seconds"] == 16
    assert len(result["prompt_blocks"]) == 2
    assert result["prompt_blocks"][0]["duration_seconds"] == 10
    assert result["prompt_blocks"][0]["shot_count"] == 3
    assert result["prompt_blocks"][1]["duration_seconds"] == 6
    assert result["prompt_blocks"][1]["shot_count"] == 1
    assert result["prompt_blocks"][1]["continuation_from_block_id"] == "block_1"
    assert result["continuation_lineage"][0]["continuation_from_block_id"] == "block_1"
    assert "Continuation requirement: continue from block_1" in result["final_compiled_prompt_text"]
    assert "vertical cinematic commercial look" in result["final_compiled_prompt_text"]
