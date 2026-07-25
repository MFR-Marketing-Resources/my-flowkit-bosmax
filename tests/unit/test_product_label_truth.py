"""Product label truth — SEV-1 regression for MWTCB package drift.

The catalog/display name is ``Minyak Warisan Tok Cap Burung 25ml`` but the
owner-supplied physical product photographs prove that ``TOK`` is not printed on
the bottle. They also prove a compact, moderately tall, rectangular flat-front
bottle rather than the stale tall/narrow AI photoshoot previously attached to
the product row.

These tests pin the separation between catalog identity and physical package
truth, the exact printed label lines, the real teal/cream/gold label layout, the
verified compact-rectangular geometry, and the rule that structured truth outranks a
conflicting visual reference.
"""
import inspect

from agent.services import canonical_prompt_compiler as c
from agent.services import product_physics
from agent.services.product_lock_builder import build_product_lock, resolve_schema_entry


MWTCB = {
    "id": "6483d624-a03d-4933-9bba-6ca2e5f7b6fd",
    "product_display_name": "Minyak Warisan Tok Cap Burung 25ml",
    "raw_product_title": "Minyak Warisan Tok Cap Burung 25ml",
    "product_short_name": "Minyak Cap Burung",
    "category": "herbal oil",
}

CATALOG_NAME = "Minyak Warisan Tok Cap Burung 25ml"
SHORTHAND = "Minyak Cap Burung"
PRINTED_LABEL_LINES = [
    "MINYAK WARISAN",
    "CAP BURUNG",
    "Sejak 1958",
    "Petua Turun Temurun",
    "25ml",
]


def _hybrid_shots() -> str:
    shots = c._default_shot_plan(
        "HYBRID",
        product=MWTCB,
        shot_count=2,
        block_index=1,
        total_blocks=2,
        family="wellness",
        angle_hint="rutin malam",
        angle_signal="",
        trigger_id="",
        cta_type="",
    )
    return "\n".join(shots)


def test_catalog_name_remains_metadata_identity_not_label_copy():
    text = _hybrid_shots()
    assert CATALOG_NAME in text
    assert SHORTHAND not in text.replace(CATALOG_NAME, "")


def test_schema_separates_catalog_name_from_exact_physical_label():
    entry = resolve_schema_entry(MWTCB)
    assert entry is not None
    assert entry["product_id"] == "MWTCB_25ML_CAP_BURUNG"
    assert entry["product_name"] == CATALOG_NAME
    assert entry["printed_label_lines"] == PRINTED_LABEL_LINES
    assert "TOK" in entry["forbidden_printed_label_tokens"]

    label = entry["label_lock"]
    layout = entry["label_layout_lock"]
    truth = entry["product_truth_ref"]
    conflict = entry["reference_conflict_policy"]

    assert "physical bottle label does not" in label
    assert "must never be inserted" in label
    assert "teal rectangular label field" in label
    assert "cream ornamental" in label
    assert "plain cream sticker" in label

    assert "MINYAK WARISAN" in layout
    assert "CAP BURUNG" in layout
    assert "bird-on-leafy-branch" in layout
    assert "Sejak 1958" in layout
    assert "Petua Turun Temurun" in layout
    assert "25ml" in layout

    for geometry in (
        "compact rectangular",
        "moderately tall",
        "flat front",
        "nearly vertical sides",
        "low rounded shoulders",
        "short clear-glass neck",
        "thick clear glass base",
    ):
        assert geometry in truth

    for stale_trait in ("TOK", "extremely squat", "tall/narrow/long-neck", "stale"):
        assert stale_trait in conflict


def test_product_lock_emits_physical_label_and_compact_rectangular_geometry_for_all_lanes():
    for is_video in (True, False):
        lock = build_product_lock(
            MWTCB,
            is_video=is_video,
            has_product_reference=True,
        )
        assert lock["matched_product_id"] == "MWTCB_25ML_CAP_BURUNG"
        identity = lock["identity_lock"]
        blob = " ".join(v for v in lock.values() if isinstance(v, str))

        assert "LABEL TEXT LOCK" in identity
        assert "never re-typeset, shorten, translate, or restyle" in identity
        assert "never add dosage, usage, or instruction text" in identity

        assert "physical bottle label does not print TOK" in identity
        assert "must never be inserted" in identity
        assert "teal rectangular label field" in identity
        assert "plain cream sticker" in identity

        for geometry in (
            "compact rectangular",
            "moderately tall",
            "low rounded shoulders",
            "short clear-glass neck",
            "thick clear glass base",
        ):
            assert geometry in blob


def test_structured_truth_outranks_a_conflicting_attached_reference():
    lock = build_product_lock(
        MWTCB,
        is_video=False,
        has_product_reference=True,
    )
    reference = lock["reference_lock"]
    no_modification = lock["no_modification_lock"]

    assert "supporting evidence" in reference
    assert "hard visual and physical-scale truth only for details that agree" in reference
    assert "not mood or style inspiration" in reference
    assert "structured bottle geometry" in reference
    assert "final authority" in reference
    assert "tall or narrow body" in reference
    assert "different teal coverage" in reference
    assert "ignore that conflicting feature" in reference

    assert "structured product truth" in no_modification
    assert "only where it agrees" in no_modification


def test_text_only_lane_still_receives_exact_physical_label_authority():
    lock = build_product_lock(
        MWTCB,
        is_video=True,
        has_product_reference=False,
    )
    identity = lock["identity_lock"]

    for printed_line in PRINTED_LABEL_LINES:
        assert printed_line in identity
    assert "FORBIDDEN PRINTED LABEL TOKENS" in identity
    assert "MINYAK WARISAN TOK" in identity
    assert "attached reference image" not in lock["reference_lock"]
    assert lock["reference_lock"] == ""


def test_passing_scale_contract_is_not_rewritten_by_label_fix():
    lock = build_product_lock(
        MWTCB,
        is_video=False,
        has_product_reference=True,
    )
    scale = lock["scale_lock"]
    for phrase in (
        "compact pocket-size",
        "moderately tall glass bottle",
        "never rewrite it as extremely squat",
        "shorter than an adult palm",
        "two fingers wide",
        "small handheld household herbal-oil bottle",
        "oversized medicine bottle",
        "dominate the hand",
        "natural handheld depth plane",
        "closer to the camera lens",
    ):
        assert phrase in scale


def test_catalog_short_name_never_becomes_the_visual_alias():
    assert c._product_visual_alias(MWTCB, "wellness") == CATALOG_NAME
    assert c._product_visual_alias(
        {**MWTCB, "visual_display_name": "MWTCB hero"},
        "wellness",
    ) == "MWTCB hero"


def test_no_dosage_or_invented_label_directives_in_templates():
    bank = c._family_clause_bank("wellness")
    joined = " ".join(str(v) for v in bank.values())
    assert "dosage" not in joined.lower()
    assert "dosage" not in _hybrid_shots().lower()
    assert "dosage-format" not in inspect.getsource(product_physics)
