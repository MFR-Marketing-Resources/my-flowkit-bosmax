"""Montage R1 — per-scene reference policy (test-first)."""
import pytest

from agent.services.montage_scene_reference_policy import (
    ERR_SCENE_PRODUCT_MEDIA_REQUIRED,
    ERR_SCENE_REFERENCE_INHERIT_MISSING,
    ERR_UNKNOWN_SCENE_REFERENCE_POLICY,
    SceneReferenceDeclaration,
    SceneReferencePolicy,
    parse_scene_reference_policy,
    policy_requires_product_media,
    validate_scene_reference_declaration,
    validate_scene_reference_set,
)
from agent.services import flow_mode_reference_contract as refc


def test_policy_enum_covers_brief_values():
    expected = {
        "NONE", "PRODUCT_ANCHOR", "START_FRAME", "START_END_FRAMES",
        "AVATAR_PRODUCT", "INGREDIENT_REFERENCES", "INHERIT_PREVIOUS_CLIP",
    }
    assert {p.value for p in SceneReferencePolicy} == expected


def test_unknown_policy_fails_closed():
    with pytest.raises(ValueError) as ei:
        parse_scene_reference_policy("PROMPT_VIDEO_3")
    assert ERR_UNKNOWN_SCENE_REFERENCE_POLICY in str(ei.value)


def test_product_anchor_requires_product_media():
    decl = SceneReferenceDeclaration(
        scene_id="s1",
        policy=SceneReferencePolicy.PRODUCT_ANCHOR,
    )
    ok, code, detail = validate_scene_reference_declaration(decl)
    assert not ok
    assert code == ERR_SCENE_PRODUCT_MEDIA_REQUIRED
    assert "product" in detail.lower()


def test_product_anchor_with_media_passes_hybrid_contract():
    decl = SceneReferenceDeclaration(
        scene_id="s1",
        policy=SceneReferencePolicy.PRODUCT_ANCHOR,
        product_media_id="prod-media-1",
    )
    ok, code, detail = validate_scene_reference_declaration(decl)
    assert ok, detail
    assert code is None
    # Existing contract still owns HYBRID = exactly 1
    assert refc.reference_bounds("F2V", source_mode="HYBRID") == (1, 1)


def test_start_end_frames_requires_two_refs():
    decl = SceneReferenceDeclaration(
        scene_id="s2",
        policy=SceneReferencePolicy.START_END_FRAMES,
        reference_media_ids=("start-only",),
        product_media_id="p",
    )
    ok, code, detail = validate_scene_reference_declaration(decl)
    assert not ok
    assert "START_END_FRAMES" in (detail or "")


def test_start_end_frames_valid():
    decl = SceneReferenceDeclaration(
        scene_id="s2",
        policy=SceneReferencePolicy.START_END_FRAMES,
        reference_media_ids=("start", "end"),
    )
    ok, code, detail = validate_scene_reference_declaration(decl)
    assert ok, detail


def test_ingredient_references_use_i2v_bounds():
    # 1 ref fails I2V
    bad = SceneReferenceDeclaration(
        scene_id="s3",
        policy=SceneReferencePolicy.INGREDIENT_REFERENCES,
        reference_media_ids=("only-one",),
        product_media_id="p",
    )
    ok, code, _ = validate_scene_reference_declaration(bad)
    assert not ok
    assert code == refc.ERR_REFERENCE_COUNT_CONTRACT

    good = SceneReferenceDeclaration(
        scene_id="s3",
        policy=SceneReferencePolicy.INGREDIENT_REFERENCES,
        reference_media_ids=("char", "scene"),
    )
    ok2, _, detail2 = validate_scene_reference_declaration(good)
    assert ok2, detail2


def test_none_policy_is_t2v_zero_refs():
    decl = SceneReferenceDeclaration(
        scene_id="s0",
        policy=SceneReferencePolicy.NONE,
        reference_media_ids=(),
    )
    ok, _, detail = validate_scene_reference_declaration(decl)
    assert ok, detail


def test_inherit_requires_previous_clip():
    decl = SceneReferenceDeclaration(
        scene_id="s4",
        policy=SceneReferencePolicy.INHERIT_PREVIOUS_CLIP,
    )
    ok, code, _ = validate_scene_reference_declaration(decl)
    assert not ok
    assert code == ERR_SCENE_REFERENCE_INHERIT_MISSING

    ok2, _, d2 = validate_scene_reference_declaration(
        SceneReferenceDeclaration(
            scene_id="s4",
            policy=SceneReferencePolicy.INHERIT_PREVIOUS_CLIP,
            previous_clip_media_id="clip-prev",
        )
    )
    assert ok2, d2


def test_set_validation_collects_violations():
    decls = [
        SceneReferenceDeclaration("a", SceneReferencePolicy.PRODUCT_ANCHOR, product_media_id="p1"),
        SceneReferenceDeclaration("b", SceneReferencePolicy.PRODUCT_ANCHOR),  # missing
    ]
    ok, violations = validate_scene_reference_set(decls)
    assert not ok
    assert len(violations) == 1
    assert violations[0]["scene_id"] == "b"


def test_existing_per_mode_contract_unchanged():
    # Guard: Montage must not weaken the job-level contract.
    assert refc.reference_bounds("I2V") == (2, 3)
    assert refc.reference_bounds("F2V", source_mode="HYBRID") == (1, 1)
    assert policy_requires_product_media(SceneReferencePolicy.PRODUCT_ANCHOR)
    assert not policy_requires_product_media(SceneReferencePolicy.NONE)
