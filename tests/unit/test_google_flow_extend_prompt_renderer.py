"""Behavioral proof for extension-native prompt representations (manual research)."""
from __future__ import annotations

from copy import deepcopy

import pytest

from agent.services.google_flow_extend_prompt_renderer import (
    ExtendPromptValidationError,
    dialogue_slice_is_natural_boundary,
    validate_flow_extend_prompt,
)
from agent.services.ugc_video_prompt_compiler_service import (
    COMPILER_VERSION,
    canonical_package_fingerprint,
    compile_ugc_video_prompt,
)

PRODUCT = {
    "id": "fixture-extend-renderer-product",
    "name": "Minyak Warisan Tok Cap Burung 25ml",
    "product_display_name": "Minyak Warisan Tok Cap Burung 25ml",
    "category": "Health & Personal Care",
}
COPY = {
    "copy_source": "selected_copy_set",
    "formula_family": "PAS",
    "angle": "Rutin malam yang lebih tenang untuk anak dan ibu bapa",
    "hook": "Anak susah tidur malam kerana perut kembung?",
    "subhook": (
        "Setiap kali anak menangis, hati ibu pun turut terganggu. "
        "Tidur tak lena, esok pagi badan pun letih."
    ),
    "usps": [
        "Minyak Warisan Tok Cap Burung 25ml dipercayai melegakan perut kembung dan angin dalam badan.",
        "Formula tradisional yang diwarisi turun-temurun, sesuai untuk kegunaan seisi keluarga.",
        "Saiz 25ml mudah dibawa ke mana-mana, sedia digunakan bila-bila masa.",
    ],
    "cta": "Cuba sapukan pada perut anak malam ini. Klik pautan untuk dapatkan botol pertama anda.",
}

MODE_MATRIX = {
    "T2V": {"mode": "T2V", "source_mode": "T2V"},
    "HYBRID": {"mode": "F2V", "source_mode": "HYBRID"},
    "FRAMES": {"mode": "F2V", "source_mode": "FRAMES"},
    "INGREDIENTS": {"mode": "I2V", "source_mode": "INGREDIENTS"},
}


def _compile(source_key: str, duration: int = 16) -> dict:
    cfg = MODE_MATRIX[source_key]
    return compile_ugc_video_prompt(
        product=deepcopy(PRODUCT),
        approved_package={"scene_context": "a calm lived-in bedroom at night"},
        mode=cfg["mode"],
        source_mode=cfg["source_mode"],
        generation_mode="EXTEND",
        engine_duration_target="GOOGLE_FLOW",
        requested_total_duration_seconds=duration,
        target_language="BM_MS",
        copy_intelligence=deepcopy(COPY),
    )


@pytest.mark.parametrize("source_key", list(MODE_MATRIX))
@pytest.mark.parametrize("duration,expected_blocks", [(16, 2), (24, 3)])
def test_representation_contract_all_modes(source_key: str, duration: int, expected_blocks: int):
    result = _compile(source_key, duration)
    blocks = result["prompt_blocks"]
    assert len(blocks) == expected_blocks

    b1 = blocks[0]
    assert b1["initial_generation_prompt_text"]
    assert b1["flow_extend_prompt_text"] in (None, "")
    assert b1["independent_block_prompt_text"]
    assert b1["engine_prompt_text"] == b1["independent_block_prompt_text"]
    assert b1["prompt_representation"] == "INITIAL_GENERATION"
    assert "SECTION 1 - ROLE & OBJECTIVE" in b1["engine_prompt_text"]

    for block in blocks[1:]:
        extend = block["flow_extend_prompt_text"]
        independent = block["independent_block_prompt_text"]
        assert extend
        assert independent
        assert extend != independent
        assert block["engine_prompt_text"] == independent
        assert extend.strip().lower().startswith("extend this video")
        assert "you are generating" not in extend.lower().splitlines()[0]
        assert "You are generating an 8-second" not in extend
        assert "SECTION 1 - ROLE & OBJECTIVE" not in extend
        assert "PRODUCT IDENTITY LOCK" not in extend
        assert "BlockAllocation" not in extend
        assert "WPS" not in extend
        assert block["prompt_purpose"] == "MANUAL_EXTENSION_RESEARCH"
        assert block["continuation_source"] == "PREVIOUS_GENERATED_VIDEO"
        assert block["previous_block_index"] == block["block_index"] - 1
        validate_flow_extend_prompt(extend, independent_block_prompt_text=independent)

        # Content contract
        lower = extend.lower()
        assert "no cut" in lower or "no reset" in lower
        assert block["exact_dialogue_slice"] in extend or not block["exact_dialogue_slice"]
        assert "no captions" in lower or "no on-screen text" in lower or "no captions, subtitles" in lower
        assert "hook" in lower  # "no repeated hook"
        assert block["audio_seam_contract"] is not None

        # Mode-specific: no restart from references / uploaded frame.
        if source_key == "FRAMES":
            assert "uploaded frame" in lower or "original" in lower or "previous generated" in lower
            assert "start from the uploaded" not in lower
        if source_key == "HYBRID":
            assert "reference" in lower or "do not restart" in lower or "identity truth" in lower
        if source_key == "INGREDIENTS":
            assert "reference" in lower
        if source_key == "T2V":
            assert "rebuild the scene from the original" in lower or "generated" in lower


@pytest.mark.parametrize("source_key", list(MODE_MATRIX))
def test_audio_seam_and_dialogue_seams(source_key: str):
    result = _compile(source_key, 16)
    blocks = result["prompt_blocks"]
    non_final = blocks[0]
    final = blocks[-1]
    assert non_final["audio_seam_contract"]["voice_active_in_final_second"] is True
    assert non_final["audio_seam_contract"]["forbid_silent_final_hold"] is True
    assert final["audio_seam_contract"]["voice_active_in_final_second"] is False

    # Production independent keeps seam-ready hold; research initial gets voice-active seam.
    assert "seam-ready hold" in non_final["engine_prompt_text"].lower()
    assert "seam-ready hold" in (non_final.get("independent_block_prompt_text") or "").lower()
    assert "naturally speaking and moving" in (non_final.get("initial_generation_prompt_text") or "").lower()
    assert non_final["initial_generation_prompt_text"] != non_final["independent_block_prompt_text"]

    # Dialogue seams natural + concat equals full plan.
    full = " ".join(
        " ".join((result["planner_result"]["full_dialogue_plan"]["full_dialogue_text"]).split()).split()
    )
    concat = " ".join(
        " ".join((b.get("exact_dialogue_slice") or "").split()) for b in blocks
    )
    assert " ".join(concat.split()) == " ".join(full.split())

    for block in blocks:
        slice_text = (block.get("exact_dialogue_slice") or "").strip()
        if not slice_text:
            continue
        if not block.get("is_final"):
            assert dialogue_slice_is_natural_boundary(slice_text, position="end"), slice_text
        assert "esok pagi badan." not in slice_text.lower()

    # CTA final only
    cta = COPY["cta"]
    assert cta in (final.get("exact_dialogue_slice") or "")
    for block in blocks[:-1]:
        assert cta not in (block.get("exact_dialogue_slice") or "")


def test_hybrid_16s_before_after_shape():
    result = _compile("HYBRID", 16)
    b2 = result["prompt_blocks"][1]
    extend = b2["flow_extend_prompt_text"]
    independent = b2["independent_block_prompt_text"]
    # BEFORE defect: independent still starts with standalone generation semantics.
    assert independent.startswith("SECTION 1 - ROLE & OBJECTIVE")
    assert "You are generating an 8-second" in independent
    # AFTER: extend is extension-native.
    assert extend.startswith("Extend this video from the exact ending of Video 1.")
    assert "You are generating" not in extend
    assert "SECTION 2 - PRODUCT TRUTH LOCK" not in extend
    words = extend.split()
    assert 80 <= len(words) <= 420


def test_24s_cta_only_final_and_block3_extend():
    result = _compile("HYBRID", 24)
    blocks = result["prompt_blocks"]
    assert len(blocks) == 3
    assert blocks[0]["flow_extend_prompt_text"] in (None, "")
    assert blocks[1]["flow_extend_prompt_text"].startswith("Extend this video")
    assert blocks[2]["flow_extend_prompt_text"].startswith("Extend this video")
    assert blocks[2]["is_final"] is True
    assert COPY["cta"] in blocks[2]["exact_dialogue_slice"]
    assert COPY["cta"] not in blocks[0]["exact_dialogue_slice"]
    assert COPY["cta"] not in blocks[1]["exact_dialogue_slice"]


def test_fingerprint_changes_when_extend_text_changes():
    result = _compile("T2V", 16)
    blocks = deepcopy(result["prompt_blocks"])
    base = canonical_package_fingerprint(
        planner_result=result["planner_result"],
        rendered_prompt_blocks=blocks,
        renderer_version=COMPILER_VERSION,
    )
    blocks[1]["flow_extend_prompt_text"] = blocks[1]["flow_extend_prompt_text"] + "\nExtra continuity note."
    changed = canonical_package_fingerprint(
        planner_result=result["planner_result"],
        rendered_prompt_blocks=blocks,
        renderer_version=COMPILER_VERSION,
    )
    assert base != changed


def test_validate_rejects_standalone_opening():
    with pytest.raises(ExtendPromptValidationError) as exc:
        validate_flow_extend_prompt(
            "You are generating an 8-second vertical commercial video block…\nContinue…"
        )
    assert exc.value.code == "EXTEND_PROMPT_STANDALONE_OPENING_FORBIDDEN"


def test_unnatural_fragment_detector():
    assert dialogue_slice_is_natural_boundary("esok pagi badan.", position="end") is False
    assert dialogue_slice_is_natural_boundary(
        "Setiap kali anak menangis, hati ibu pun turut terganggu.", position="end"
    )
    # Valid noun endings must not false-positive.
    for ok in (
        "Anak susah tidur malam.",
        "Saya jaga anak.",
        "Kasih sayang ibu.",
        "Simpan botol.",
        "Sapu minyak.",
        "Perut kembung di badan.",
        "Legakan perut.",
    ):
        assert dialogue_slice_is_natural_boundary(ok, position="end"), ok
