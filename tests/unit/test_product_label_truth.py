"""Product label truth — SEV-1 regression for the MWTCB label/packaging drift.

Live evidence (job g_c1a9b3fd6afd, 2026-07-11): the engine re-typeset the real
"Minyak Warisan Tok Cap Burung 25ml" label as the catalog shorthand
"Minyak Cap Burung" and invented dosage-instruction content, because the compiled
shot lines injected `product_short_name` and the wellness template directed
"showing dosage instructions clearly". These tests pin the repaired invariants:
canonical name in every prompt-visible surface, zero invented-label directives,
and an explicit LABEL TEXT LOCK in the product lock for every mode.
"""
import inspect

from agent.services import canonical_prompt_compiler as c
from agent.services import product_physics
from agent.services.product_lock_builder import build_product_lock

MWTCB = {
    "id": "6483d624-a03d-4933-9bba-6ca2e5f7b6fd",
    "product_display_name": "Minyak Warisan Tok Cap Burung 25ml",
    "raw_product_title": "Minyak Warisan Tok Cap Burung 25ml",
    "product_short_name": "Minyak Cap Burung",  # catalog shorthand — must NOT reach prompts
    "category": "herbal oil",
}

CANONICAL = "Minyak Warisan Tok Cap Burung 25ml"
SHORTHAND = "Minyak Cap Burung"


def _hybrid_shots() -> str:
    shots = c._default_shot_plan(
        "HYBRID", product=MWTCB, shot_count=2, block_index=1, total_blocks=2,
        family="wellness", angle_hint="rutin malam", angle_signal="", trigger_id="",
        cta_type="")
    return "\n".join(shots)


def test_shot_lines_use_the_canonical_registered_name():
    text = _hybrid_shots()
    assert CANONICAL in text
    # The bare shorthand must never appear (the canonical name does NOT contain it —
    # "Warisan Tok" sits between "Minyak" and "Cap Burung", so substring is exact).
    assert SHORTHAND not in text.replace(CANONICAL, "")


def test_catalog_short_name_never_becomes_the_visual_alias():
    assert c._product_visual_alias(MWTCB, "wellness") == CANONICAL
    # An explicit operator-set visual override is still honoured.
    assert c._product_visual_alias(
        {**MWTCB, "visual_display_name": "MWTCB hero"}, "wellness") == "MWTCB hero"


def test_no_dosage_or_invented_label_directives_in_templates():
    bank = c._family_clause_bank("wellness")
    joined = " ".join(str(v) for v in bank.values())
    assert "dosage" not in joined.lower()
    assert "dosage" not in _hybrid_shots().lower()
    # product_physics handling cues must not invite invented label content either.
    assert "dosage-format" not in inspect.getsource(product_physics)


def test_product_lock_carries_label_text_lock_for_every_mode():
    for is_video in (True, False):
        lock = build_product_lock(MWTCB, is_video=is_video, has_product_reference=True)
        identity = lock["identity_lock"]
        assert "LABEL TEXT LOCK" in identity
        assert "never re-typeset, shorten, translate, or restyle" in identity
        assert "never add dosage, usage, or instruction text" in identity
