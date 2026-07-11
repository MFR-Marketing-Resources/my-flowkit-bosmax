"""Extension SCALE CONTINUITY LOCK — regression for the bottle-shrink drift in
native Google Flow extend blocks.

Root cause (prompt-level): a native continuation carries NO attached reference image,
so the block-1 "reference image = scale truth" lock is inert, and the remaining scale
language is enlargement-only — letting the product drift SMALLER across an invented
pour/cap/re-grip. The fix re-anchors scale to the previous clip's final frame and makes
the lock BIDIRECTIONAL, for EVERY continuation block (2..N) and ANY product.
"""
from agent.services import canonical_prompt_compiler as c

_KEY = "SCALE CONTINUITY LOCK (extension)"

MWTCB = {
    "product_display_name": "Minyak Warisan Tok Cap Burung 25ml",
    "product_short_name": "Minyak Cap Burung", "brand": "MWTCB", "category": "herbal oil",
}
OTHER = {
    "product_display_name": "BOSMAX Roll-On 10ml",
    "product_short_name": "BOSMAX", "brand": "BOSMAX", "category": "roll-on",
}


def _s3(product, *, is_continuation):
    return c._section_3_continuity(
        "F2V", product=product, presenter_prose="Presenter is a Malaysian woman.",
        asset_role_map=None, style_scene_source=None,
        is_continuation=is_continuation, scene_context="a calm home at night")


def test_continuation_block_gets_bidirectional_frame_anchored_scale_lock():
    s3 = _s3(MWTCB, is_continuation=True)
    assert _KEY in s3
    # the missing anti-shrink direction that caused the drift
    assert "must not shrink and must not enlarge" in s3
    # anchored to the previous clip's FINAL FRAME, not the absent reference image
    assert "FINAL FRAME of the previous clip is the scale truth" in s3
    assert "no separate attached reference image in this block" in s3
    # covers the invented pour/cap/re-grip motions where the drift happened
    for word in ("pour", "cap", "re-grip"):
        assert word in s3, word


def test_opening_block_1_is_untouched():
    # block 1 keeps its reference-image anchor and must NOT get the extension clause
    assert _KEY not in _s3(MWTCB, is_continuation=False)


def test_scale_lock_is_product_agnostic():
    s3 = _s3(OTHER, is_continuation=True)
    assert _KEY in s3
    assert "BOSMAX" in s3                                   # product name injected, not hardcoded
    assert "must not shrink and must not enlarge" in s3


def test_gate_covers_every_block_index_via_is_continuation():
    # render_block computes `is_continuation = block_index > 1`, and _section_3_continuity emits
    # the lock iff is_continuation. Compose the two across indices 1..7: block 1 has no lock;
    # blocks 2,3,5,7 (and every N>1) do. This is the guarantee for chains of any length.
    for idx in (1, 2, 3, 5, 7):
        is_cont = idx > 1
        s3 = _s3(MWTCB, is_continuation=is_cont)
        assert (_KEY in s3) is is_cont, f"block {idx}: expected lock={is_cont}"


def test_render_block_source_declares_block_index_gate():
    # Guard the gate itself: the mapping that turns block_index into is_continuation must remain
    # `block_index > 1` (if a refactor changed it, mid-chain blocks could silently lose the lock).
    import inspect
    src = inspect.getsource(c.render_block)
    assert "is_continuation = block_index > 1" in src
