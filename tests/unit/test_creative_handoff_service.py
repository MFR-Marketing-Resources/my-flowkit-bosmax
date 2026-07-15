"""Creative Intelligence Round 5 — gated generation handoff service tests."""
import pytest

from agent.db import crud
from agent.services import avatar_registry
from agent.services import creative_scene_prompt_service as _scene
from agent.services import creative_camera_preset_service as _camera
from agent.services import creative_setup_service as _setup
from agent.services import creative_handoff_service as svc


async def _count(table):
    db = await crud.get_db()
    cur = await db.execute(f"SELECT COUNT(*) FROM {table}")
    return (await cur.fetchone())[0]


def _valid_ids():
    return (
        avatar_registry.list_pool()[0]["avatar_code"],
        _scene.library_templates()[0]["template_id"],
        _camera.named_presets()[0]["preset_code"],
    )


async def _approved_product():
    product = await crud.create_product(
        source="MANUAL", raw_product_title="Handoff Test Product",
        product_display_name="Handoff Test Product", product_short_name="Handoff",
        category="Home & Living",
    )
    avatar, scene, camera = _valid_ids()
    await _setup.save_creative_selection(
        product["id"], selected_avatar_code=avatar,
        selected_scene_template_id=scene, selected_camera_preset_code=camera,
    )
    await _setup.review_creative_selection(product["id"], "APPROVE")
    return product, avatar, scene, camera


@pytest.mark.asyncio
async def test_handoff_for_approved_selection_resolves_placeholders():
    product, avatar, scene, camera = await _approved_product()
    h = await svc.prepare_generation_handoff(product["id"])

    assert h["selection_status"] == "APPROVED"
    assert h["auto_generated"] is False
    assert h["requires_confirmation"] is True
    assert h["handoff_status"] == "PREVIEW_ONLY_REQUIRES_CONFIRMATION"
    assert h["avatar"]["avatar_code"] == avatar
    assert h["scene_template"]["template_id"] == scene
    assert h["camera_preset"]["preset_code"] == camera
    assert h["provenance"]["source"] == "CREATIVE_HANDOFF_v1"

    # [PRODUCT] resolves to the product name; [AVATAR] resolves to presenter prose.
    resolved = h["resolved_prompt_preview"]
    assert "Handoff Test Product" in resolved
    assert "[PRODUCT]" not in resolved
    assert "[AVATAR]" not in resolved
    assert "The presenter is" in resolved  # avatar_registry.presenter_prose output
    assert h["avatar"]["resolved_descriptor"].startswith("The presenter is")

    # The raw template is preserved UNRESOLVED alongside the resolved preview.
    assert "[AVATAR]" in h["scene_template"]["raw_prompt_template"]


@pytest.mark.asyncio
async def test_handoff_blocked_for_draft_selection():
    product = await crud.create_product(
        source="MANUAL", raw_product_title="Draft", product_display_name="Draft",
        product_short_name="Draft", category="Beauty & Personal Care",
    )
    avatar, _, _ = _valid_ids()
    await _setup.save_creative_selection(product["id"], selected_avatar_code=avatar)  # stays DRAFT
    with pytest.raises(ValueError, match="SELECTION_NOT_APPROVED"):
        await svc.prepare_generation_handoff(product["id"])


@pytest.mark.asyncio
async def test_handoff_blocked_for_rejected_selection():
    product = await crud.create_product(
        source="MANUAL", raw_product_title="Rej", product_display_name="Rej",
        product_short_name="Rej", category="Home & Living",
    )
    avatar, _, _ = _valid_ids()
    await _setup.save_creative_selection(product["id"], selected_avatar_code=avatar)
    await _setup.review_creative_selection(product["id"], "REJECT")
    with pytest.raises(ValueError, match="SELECTION_NOT_APPROVED"):
        await svc.prepare_generation_handoff(product["id"])


@pytest.mark.asyncio
async def test_handoff_blocked_for_missing_selection_and_product():
    product = await crud.create_product(
        source="MANUAL", raw_product_title="NoSel", product_display_name="NoSel",
        product_short_name="NoSel", category="Home & Living",
    )
    with pytest.raises(ValueError, match="SELECTION_NOT_FOUND"):
        await svc.prepare_generation_handoff(product["id"])
    with pytest.raises(ValueError, match="PRODUCT_NOT_FOUND"):
        await svc.prepare_generation_handoff("does-not-exist")


@pytest.mark.asyncio
async def test_handoff_fail_closed_on_invalid_avatar_in_approved_selection():
    # Craft an APPROVED selection carrying a bad avatar code (bypassing save's
    # validation via direct crud) — the handoff boundary must re-validate.
    product = await crud.create_product(
        source="MANUAL", raw_product_title="Bad", product_display_name="Bad",
        product_short_name="Bad", category="Home & Living",
    )
    await crud.upsert_creative_product_selection(
        product_id=product["id"], selected_avatar_code="NOT_A_REAL_AVATAR",
        selected_scene_template_id="SCN-0001", selected_camera_preset_code="HOOK_A",
        status="APPROVED",
    )
    with pytest.raises(ValueError, match="INVALID_AVATAR_CODE"):
        await svc.prepare_generation_handoff(product["id"])


@pytest.mark.asyncio
async def test_handoff_is_read_only_no_mutation():
    product, *_ = await _approved_product()
    sel_n = await _count("creative_product_selection")
    prod_n = await _count("product")
    art_n = await _count("generated_artifact")
    pkg_n = await _count("workspace_generation_package")
    run_n = await _count("production_run")

    await svc.prepare_generation_handoff(product["id"])

    assert await _count("creative_product_selection") == sel_n
    assert await _count("product") == prod_n
    assert await _count("generated_artifact") == art_n
    assert await _count("workspace_generation_package") == pkg_n
    assert await _count("production_run") == run_n


def test_invariant_generation_services_do_not_read_selection_or_handoff():
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    generation_files = [
        "agent/services/canonical_prompt_compiler.py",
        "agent/services/make_video.py",
        "agent/services/workspace_execution_package_service.py",
        "agent/services/copy_grounding_service.py",
        "agent/services/copy_binding_service.py",
    ]
    for rel in generation_files:
        text = (repo_root / rel).read_text(encoding="utf-8")
        assert "creative_handoff_service" not in text
        assert "creative_setup_service" not in text
        assert "creative_product_selection" not in text
