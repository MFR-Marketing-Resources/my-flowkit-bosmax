"""Creative Intelligence Round 3 — camera / video preset service tests."""
import pytest

from agent.db import crud
from agent.services import creative_camera_preset_service as svc


async def _count(table):
    db = await crud.get_db()
    cur = await db.execute(f"SELECT COUNT(*) FROM {table}")
    return (await cur.fetchone())[0]


def test_library_loads_all_sections_with_expected_counts():
    lib = svc._library()
    assert lib["library_version"] == svc.LIBRARY_SOURCE
    c = lib["counts"]
    assert c == {
        "shot_distances": 7, "camera_angles": 8, "camera_movements": 15,
        "ecomm_shot_types": 15, "named_presets": 17, "block_content_mapping": 12,
    }
    assert set(svc.block_groups()) == {"HOOK", "BODY", "CTA", "TRANS"}


def test_named_presets_and_block_mapping_cross_reference_resolves():
    presets = {p["preset_code"] for p in svc.named_presets()}
    assert len(presets) == 17
    # every preset referenced by the block mapping must resolve to a named preset
    for m in svc.block_content_mapping():
        assert m["recommended_preset"] in presets
        for alt in ("alt_preset_1", "alt_preset_2"):
            if m.get(alt):
                assert m[alt] in presets
    # library declares zero dangling references
    assert svc._library()["dangling_preset_references"] == []


def test_helper_columns_and_blank_rows_are_quarantined():
    q = svc.quarantine()
    assert isinstance(q, list)
    # the helper/dropdown display columns are explicitly excluded with a reason
    assert any(row.get("section") == "HELPER_DROPDOWNS" for row in q)
    for row in q:
        assert "reason" in row


@pytest.mark.asyncio
async def test_seed_dry_run_writes_nothing():
    before = await _count("creative_camera_preset")
    report = await svc.seed_camera_presets(dry_run=True)
    assert report["dry_run"] is True
    assert report["written"] == 0
    assert report["presets_available"] == 17
    assert await _count("creative_camera_preset") == before


@pytest.mark.asyncio
async def test_seed_writes_idempotently_with_provenance():
    products_before = await _count("product")
    snap_before = await _count("product_intelligence_snapshot")
    copy_before = await _count("copy_set")

    r1 = await svc.seed_camera_presets(dry_run=False)
    assert r1["written"] == 17
    assert await _count("creative_camera_preset") == 17

    r2 = await svc.seed_camera_presets(dry_run=False)
    assert r2["written"] == 17
    assert await _count("creative_camera_preset") == 17

    rows = await crud.list_creative_camera_presets(block_group="HOOK")
    assert rows
    assert all(svc.LIBRARY_SOURCE in (row.get("provenance") or "") for row in rows)

    # No Product Truth / snapshot / Copy Set mutation.
    assert await _count("product") == products_before
    assert await _count("product_intelligence_snapshot") == snap_before
    assert await _count("copy_set") == copy_before


@pytest.mark.asyncio
async def test_recommend_for_category_returns_block_recommendations():
    result = await svc.recommend_camera_presets_for_category("Home & Living")
    assert result["cluster"] == "Home & Living"
    assert result["cluster_source"] == "EXACT"
    assert result["block_recommendation_count"] == 12
    assert result["has_recommendations"] is True
    # each recommendation resolves its recommended preset to full detail
    first = result["block_recommendations"][0]
    assert first["recommended_preset"]["preset_code"]
    assert first["recommended_preset"]["shot_type"]
    assert first["recommended_preset"]["distance_angle"]
    assert first["recommended_preset"]["movement"]
    # universal vocabulary present
    assert len(result["library"]["camera_movements"]) == 15


@pytest.mark.asyncio
async def test_block_and_content_type_filter():
    hooks = await svc.recommend_camera_presets_for_category("Beauty", block="Hook Block")
    assert hooks["block_recommendation_count"] == 3
    assert all(r["block_purpose"] == "Hook Block" for r in hooks["block_recommendations"])

    one = await svc.recommend_camera_presets_for_category("Beauty", content_type="Call to Action")
    assert one["block_recommendation_count"] == 1
    assert one["block_recommendations"][0]["recommended_preset"]["preset_code"] == "CTA_A"


@pytest.mark.asyncio
async def test_recommend_parity_manual_and_imported_product():
    imported = await crud.create_product(
        source="FASTMOSS", raw_product_title="Imported Rug", product_display_name="Imported Rug",
        product_short_name="Rug", category="Home & Living",
    )
    manual = await crud.create_product(
        source="MANUAL", raw_product_title="Manual Serum", product_display_name="Manual Serum",
        product_short_name="Serum", category="Beauty & Personal Care",
    )
    r_imp = await svc.recommend_camera_presets_for_product(imported["id"])
    r_man = await svc.recommend_camera_presets_for_product(manual["id"])
    # camera vocabulary is universal -> both products get the same 12 block recs
    assert r_imp["block_recommendation_count"] == 12
    assert r_man["block_recommendation_count"] == 12
    assert r_imp["product_id"] == imported["id"]


@pytest.mark.asyncio
async def test_unknown_category_degrades_safely():
    result = await svc.recommend_camera_presets_for_category("Totally Unknown Thing")
    assert result["cluster_source"] in ("FALLBACK", "FALLBACK_EMPTY")
    assert result["block_recommendation_count"] == 12  # universal, never crashes


@pytest.mark.asyncio
async def test_recommend_does_not_mutate_product_row():
    product = await crud.create_product(
        source="MANUAL", raw_product_title="Camera Test", product_display_name="Camera Test",
        product_short_name="CamTest", category="Home & Living",
    )
    before = await crud.get_product(product["id"])
    await svc.recommend_camera_presets_for_product(product["id"])
    after = await crud.get_product(product["id"])
    # no product-row column (incl. any camera_* columns) is written by the recommender
    assert before == after


@pytest.mark.asyncio
async def test_recommend_missing_product_raises():
    with pytest.raises(ValueError, match="PRODUCT_NOT_FOUND"):
        await svc.recommend_camera_presets_for_product("does-not-exist")


def test_invariant_generation_services_do_not_reference_camera_preset_library():
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
        assert "creative_camera_preset_service" not in text
        assert "creative_camera_preset_library" not in text
