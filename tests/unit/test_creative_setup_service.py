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
    from agent.services import creative_recipe_service as _recipe

    avatar = avatar_registry.list_pool()[0]["avatar_code"]
    tpl = _scene.library_templates()[0]
    scene = tpl["template_id"]
    # Camera now FOLLOWS the scene (derived via the scene->variation->camera bridge)
    # — the value the service persists, replacing the old independent preset pick.
    camera = _recipe.camera_for_variant(tpl.get("variant"))
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
    # Camera FOLLOWS the scene now (never a free input): a bad camera code is IGNORED
    # (the camera is derived from the chosen scene), not a validation error.
    ignored = await svc.save_creative_selection(
        product["id"], selected_scene_template_id=scene,
        selected_camera_preset_code="ZZZ_9",
    )
    assert ignored["selected_camera_preset_code"] == camera
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


@pytest.mark.asyncio
async def test_resolve_setup_review_required_blank_and_unknown_category():
    blank = await _mk_product(category="")
    unknown = await _mk_product(category="Totally Unknown Category XYZ")
    for product in (blank, unknown):
        r = await svc.resolve_creative_setup(product["id"])
        assert r["review_required"] is True
        assert r["cluster"] is None
        assert r["recommended_avatars"] == []
        assert r["recommended_scene_templates"] == []
        assert r["camera_block_recommendations"] == []
        assert r["camera_library"]["named_presets"] == []


@pytest.mark.asyncio
async def test_save_selection_fail_closed_on_review_required_category():
    product = await _mk_product(category="")
    avatar, _, _ = _valid_ids()
    with pytest.raises(ValueError, match="PRODUCT_CATEGORY_REVIEW_REQUIRED"):
        await svc.save_creative_selection(product["id"], selected_avatar_code=avatar)
    assert await _selection_rows_for(product["id"]) == 0


@pytest.mark.asyncio
async def test_avatar_patch_preserves_scene_camera_block_notes_and_resets_status():
    product = await _mk_product()
    avatar_a, scene, camera = _valid_ids()
    pool = avatar_registry.list_pool()
    avatar_b = next(
        a["avatar_code"] for a in pool if a["avatar_code"] != avatar_a
    )

    await svc.save_creative_selection(
        product["id"],
        selected_avatar_code=avatar_a,
        selected_scene_template_id=scene,
        selected_camera_preset_code=camera,
        selected_block_purpose="HOOK",
        selected_content_type="UGC",
        notes="keep-me-note",
    )
    await svc.review_creative_selection(product["id"], "APPROVE", "ship it")

    patched = await svc.update_creative_selection_avatar(
        product["id"],
        selected_avatar_code=avatar_b,
        notes_append="avatar-patch-append",
    )
    assert patched["status"] == "DRAFT"
    assert patched["selected_avatar_code"] == avatar_b
    assert patched["selected_scene_template_id"] == scene
    assert patched["selected_camera_preset_code"] == camera
    assert patched["selected_block_purpose"] == "HOOK"
    assert patched["selected_content_type"] == "UGC"
    assert "keep-me-note" in (patched.get("notes") or "")
    assert "avatar-patch-append" in (patched.get("notes") or "")
    assert patched["preview"]["avatar"]["avatar_code"] == avatar_b
    assert patched["preview"]["scene_template"]["template_id"] == scene
    assert patched["preview"]["camera_preset"]["preset_code"] == camera
    assert patched["preview"]["not_for_generation"] is True
    assert patched["provenance"]["source"] == svc.AVATAR_PATCH_SOURCE
    assert patched["provenance"]["update_kind"] == "AVATAR_ONLY"
    assert patched["provenance"]["previous_avatar_code"] == avatar_a


@pytest.mark.asyncio
async def test_avatar_patch_rejected_also_returns_to_draft():
    product = await _mk_product()
    avatar_a, scene, camera = _valid_ids()
    pool = avatar_registry.list_pool()
    avatar_b = next(a["avatar_code"] for a in pool if a["avatar_code"] != avatar_a)
    await svc.save_creative_selection(
        product["id"],
        selected_avatar_code=avatar_a,
        selected_scene_template_id=scene,
        selected_camera_preset_code=camera,
    )
    await svc.review_creative_selection(product["id"], "REJECT", "nope")
    patched = await svc.update_creative_selection_avatar(
        product["id"], selected_avatar_code=avatar_b
    )
    assert patched["status"] == "DRAFT"
    assert patched["selected_scene_template_id"] == scene
    assert patched["selected_camera_preset_code"] == camera


@pytest.mark.asyncio
async def test_avatar_patch_invalid_avatar_no_mutation():
    product = await _mk_product()
    avatar, scene, camera = _valid_ids()
    await svc.save_creative_selection(
        product["id"],
        selected_avatar_code=avatar,
        selected_scene_template_id=scene,
        selected_camera_preset_code=camera,
        notes="stable",
    )
    before = await crud.get_creative_product_selection(product["id"])
    with pytest.raises(ValueError, match="INVALID_AVATAR_CODE"):
        await svc.update_creative_selection_avatar(
            product["id"], selected_avatar_code="NOPE_XX"
        )
    after = await crud.get_creative_product_selection(product["id"])
    assert after == before


@pytest.mark.asyncio
async def test_avatar_patch_does_not_mutate_product_or_generation_tables():
    product = await _mk_product()
    avatar_a, scene, camera = _valid_ids()
    avatar_b = next(
        a["avatar_code"]
        for a in avatar_registry.list_pool()
        if a["avatar_code"] != avatar_a
    )
    await svc.save_creative_selection(
        product["id"],
        selected_avatar_code=avatar_a,
        selected_scene_template_id=scene,
        selected_camera_preset_code=camera,
    )
    before_product = await crud.get_product(product["id"])
    prod_n = await _count("product")
    art_n = await _count("generated_artifact")
    copy_n = await _count("copy_set")

    await svc.update_creative_selection_avatar(
        product["id"], selected_avatar_code=avatar_b
    )

    assert await crud.get_product(product["id"]) == before_product
    assert await _count("product") == prod_n
    assert await _count("generated_artifact") == art_n
    assert await _count("copy_set") == copy_n


@pytest.mark.asyncio
async def test_avatar_patch_review_required_product_no_write():
    product = await _mk_product(category="")
    avatar, _, _ = _valid_ids()
    with pytest.raises(ValueError, match="PRODUCT_CATEGORY_REVIEW_REQUIRED"):
        await svc.update_creative_selection_avatar(
            product["id"], selected_avatar_code=avatar
        )
    assert await _selection_rows_for(product["id"]) == 0