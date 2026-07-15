"""Creative Intelligence Round 4 — unified setup + saved selection tests."""
import pytest

from agent.db import crud
from agent.services import avatar_registry
from agent.services import creative_scene_prompt_service as _scene
from agent.services import creative_camera_preset_service as _camera
from agent.services import creative_setup_service as svc


async def _count(table):
    db = await crud.get_db()
    cur = await db.execute(f"SELECT COUNT(*) FROM {table}")
    return (await cur.fetchone())[0]


async def _selection_rows_for(product_id):
    db = await crud.get_db()
    cur = await db.execute(
        "SELECT COUNT(*) FROM creative_product_selection WHERE product_id=?", (product_id,)
    )
    return (await cur.fetchone())[0]


def _valid_ids():
    avatar = avatar_registry.list_pool()[0]["avatar_code"]
    scene = _scene.library_templates()[0]["template_id"]
    camera = _camera.named_presets()[0]["preset_code"]
    return avatar, scene, camera


async def _mk_product(category="Home & Living", source="MANUAL"):
    return await crud.create_product(
        source=source, raw_product_title="Setup Test", product_display_name="Setup Test",
        product_short_name="Setup", category=category,
    )


@pytest.mark.asyncio
async def test_resolve_setup_composes_all_three_for_imported_and_manual():
    imported = await _mk_product(category="Home & Living", source="FASTMOSS")
    manual = await _mk_product(category="Beauty & Personal Care", source="MANUAL")
    r_imp = await svc.resolve_creative_setup(imported["id"])
    r_man = await svc.resolve_creative_setup(manual["id"])
    for r, cluster in ((r_imp, "Home & Living"), (r_man, "Beauty")):
        assert r["cluster"] == cluster
        assert len(r["recommended_avatars"]) >= 1
        assert len(r["recommended_scene_templates"]) >= 1
        assert len(r["camera_block_recommendations"]) == 12
        assert len(r["camera_library"]["named_presets"]) == 17
        assert r["saved_selection"] is None  # none saved yet


@pytest.mark.asyncio
async def test_resolve_setup_missing_product_raises():
    with pytest.raises(ValueError, match="PRODUCT_NOT_FOUND"):
        await svc.resolve_creative_setup("does-not-exist")


@pytest.mark.asyncio
async def test_save_selection_validates_ids_and_starts_draft():
    product = await _mk_product()
    avatar, scene, camera = _valid_ids()
    saved = await svc.save_creative_selection(
        product["id"], selected_avatar_code=avatar,
        selected_scene_template_id=scene, selected_camera_preset_code=camera,
        notes="manual override note",
    )
    assert saved["status"] == "DRAFT"
    assert saved["selected_avatar_code"] == avatar
    assert saved["selected_scene_template_id"] == scene
    assert saved["selected_camera_preset_code"] == camera
    assert saved["selection_id"]
    # preview composed, placeholders preserved, marked not-for-generation
    pv = saved["preview"]
    assert pv["not_for_generation"] is True
    assert pv["avatar"]["avatar_code"] == avatar
    assert "[PRODUCT]" in (pv["scene_template"]["full_prompt_template"] or "")
    assert pv["camera_preset"]["preset_code"] == camera


@pytest.mark.asyncio
async def test_save_selection_rejects_invalid_ids():
    product = await _mk_product()
    avatar, scene, camera = _valid_ids()
    with pytest.raises(ValueError, match="INVALID_AVATAR_CODE"):
        await svc.save_creative_selection(product["id"], selected_avatar_code="NOPE_XX")
    with pytest.raises(ValueError, match="INVALID_SCENE_TEMPLATE_ID"):
        await svc.save_creative_selection(product["id"], selected_scene_template_id="SCN-9999")
    with pytest.raises(ValueError, match="INVALID_CAMERA_PRESET_CODE"):
        await svc.save_creative_selection(product["id"], selected_camera_preset_code="ZZZ_9")
    with pytest.raises(ValueError, match="PRODUCT_NOT_FOUND"):
        await svc.save_creative_selection("nope", selected_avatar_code=avatar)


@pytest.mark.asyncio
async def test_save_is_idempotent_update_safe_one_row_per_product():
    product = await _mk_product()
    avatar, scene, camera = _valid_ids()
    s1 = await svc.save_creative_selection(product["id"], selected_avatar_code=avatar)
    n1 = await _selection_rows_for(product["id"])
    s2 = await svc.save_creative_selection(
        product["id"], selected_avatar_code=avatar, selected_scene_template_id=scene
    )
    n2 = await _selection_rows_for(product["id"])
    assert n1 == n2 == 1  # exactly one row per product (update-safe)
    assert s1["selection_id"] == s2["selection_id"]  # stable across updates
    assert s1["created_at"] == s2["created_at"]
    assert s2["selected_scene_template_id"] == scene


@pytest.mark.asyncio
async def test_resolve_setup_includes_saved_selection():
    product = await _mk_product()
    avatar, _, _ = _valid_ids()
    await svc.save_creative_selection(product["id"], selected_avatar_code=avatar)
    r = await svc.resolve_creative_setup(product["id"])
    assert r["saved_selection"] is not None
    assert r["saved_selection"]["selected_avatar_code"] == avatar
    assert r["saved_selection"]["preview"]["not_for_generation"] is True


@pytest.mark.asyncio
async def test_review_transitions_and_guards():
    product = await _mk_product()
    avatar, _, _ = _valid_ids()
    await svc.save_creative_selection(product["id"], selected_avatar_code=avatar)
    approved = await svc.review_creative_selection(product["id"], "APPROVE", "looks good")
    assert approved["status"] == "APPROVED"
    assert approved["reviewer_note"] == "looks good"
    assert approved["reviewed_at"]
    # already APPROVED -> not in DRAFT
    with pytest.raises(ValueError, match="NOT_IN_DRAFT"):
        await svc.review_creative_selection(product["id"], "REJECT")
    # invalid action
    with pytest.raises(ValueError, match="INVALID_ACTION"):
        await svc.review_creative_selection(product["id"], "MAYBE")
    # missing selection
    other = await _mk_product()
    with pytest.raises(ValueError, match="SELECTION_NOT_FOUND"):
        await svc.review_creative_selection(other["id"], "APPROVE")


@pytest.mark.asyncio
async def test_resave_after_approve_resets_to_draft():
    product = await _mk_product()
    avatar, _, _ = _valid_ids()
    await svc.save_creative_selection(product["id"], selected_avatar_code=avatar)
    await svc.review_creative_selection(product["id"], "APPROVE")
    resaved = await svc.save_creative_selection(product["id"], selected_avatar_code=avatar)
    assert resaved["status"] == "DRAFT"  # editing the config re-opens review


@pytest.mark.asyncio
async def test_save_does_not_mutate_product_or_other_tables():
    product = await _mk_product()
    before_product = await crud.get_product(product["id"])
    prod_n = await _count("product")
    copy_n = await _count("copy_set")
    snap_n = await _count("product_intelligence_snapshot")
    draft_n = await _count("product_intelligence_review_draft")
    art_n = await _count("generated_artifact")

    avatar, scene, camera = _valid_ids()
    await svc.save_creative_selection(
        product["id"], selected_avatar_code=avatar,
        selected_scene_template_id=scene, selected_camera_preset_code=camera,
    )

    after_product = await crud.get_product(product["id"])
    assert before_product == after_product  # incl. all camera_* columns untouched
    assert await _count("product") == prod_n
    assert await _count("copy_set") == copy_n
    assert await _count("product_intelligence_snapshot") == snap_n
    assert await _count("product_intelligence_review_draft") == draft_n
    assert await _count("generated_artifact") == art_n


def test_invariant_generation_services_do_not_reference_creative_setup():
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    generation_files = [
        "agent/services/canonical_prompt_compiler.py",
        "agent/services/ai_copy_assist_service.py",
        "agent/services/copy_grounding_service.py",
        "agent/services/copy_binding_service.py",
        "agent/services/workspace_execution_package_service.py",
    ]
    for rel in generation_files:
        text = (repo_root / rel).read_text(encoding="utf-8")
        assert "creative_setup_service" not in text
        assert "creative_product_selection" not in text
