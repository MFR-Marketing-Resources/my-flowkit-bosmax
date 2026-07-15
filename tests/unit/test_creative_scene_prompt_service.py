"""Creative Intelligence Round 2 — scene / image prompt service tests."""
import pytest

from agent.db import crud
from agent.services import creative_avatar_recommendation_service as avatar_svc
from agent.services import creative_scene_prompt_service as svc


async def _count(table):
    db = await crud.get_db()
    cur = await db.execute(f"SELECT COUNT(*) FROM {table}")
    return (await cur.fetchone())[0]


def test_library_loads_with_global_config_and_templates():
    lib = svc._library()
    assert lib["library_version"] == svc.LIBRARY_SOURCE
    assert lib["template_count"] == len(svc.library_templates()) == 154
    cfg = svc.global_config()
    assert cfg["style_suffix"]  # IMG_CONFIG global style suffix captured
    assert cfg["negative_prompt"]  # IMG_CONFIG global negative captured
    assert set(cfg["common_actions"]) == {"holding_demo", "using_in_scene", "lifestyle"}
    assert all(cfg["common_actions"].values())


def test_reconciliation_maps_all_source_categories_to_canonical_clusters():
    clusters = set(avatar_svc.canonical_clusters())
    recon = svc.category_reconciliation()
    assert len(recon) == 22  # the 22 IMAGE_PROMPTS source categories
    for row in recon:
        assert row["cluster"] in clusters  # every source cat -> a canonical cluster
        # confident reconciliation only (Round 1 resolver), never a weak fallback
        assert row["cluster_source"] in ("EXACT", "PREFIX", "KEYWORD")
    # every template inherits a confident cluster from the same resolver
    for t in svc.library_templates():
        assert t["cluster"] in clusters
        assert t["cluster_source"] in ("EXACT", "PREFIX", "KEYWORD")


def test_weak_or_blank_rows_are_quarantined_not_silently_mapped():
    # This library ingested cleanly (0 quarantine), but the contract is that weak
    # (FALLBACK) or blank rows are quarantined with a reason, never bucketed.
    q = svc.quarantine()
    assert isinstance(q, list)
    for row in q:
        assert "reason" in row and "source_row" in row
    # No template was produced from a weak reconciliation.
    assert all(t["cluster_source"] != "FALLBACK" for t in svc.library_templates())


def test_placeholders_are_preserved_unresolved():
    templates = svc.library_templates()
    # [AVATAR] present in every template; [PRODUCT] in all but a couple of
    # lifestyle rows — and NEVER resolved to a real name.
    assert all("[AVATAR]" in t["full_prompt_template"] for t in templates)
    assert sum("[PRODUCT]" in t["full_prompt_template"] for t in templates) >= 150
    # No resolved BOS_ avatar code or a concrete product leaked into a template.
    joined = " ".join(t["full_prompt_template"] for t in templates)
    assert "BOS_F_" not in joined


@pytest.mark.asyncio
async def test_seed_dry_run_writes_nothing():
    before = await _count("creative_scene_prompt")
    report = await svc.seed_scene_prompts(dry_run=True)
    assert report["dry_run"] is True
    assert report["written"] == 0
    assert report["templates_available"] == 154
    assert await _count("creative_scene_prompt") == before


@pytest.mark.asyncio
async def test_seed_writes_idempotently_with_provenance():
    products_before = await _count("product")
    snap_before = await _count("product_intelligence_snapshot")
    copy_before = await _count("copy_set")

    r1 = await svc.seed_scene_prompts(dry_run=False)
    assert r1["written"] == 154
    assert await _count("creative_scene_prompt") == 154

    # Re-seed is idempotent (upsert keyed on template_id).
    r2 = await svc.seed_scene_prompts(dry_run=False)
    assert r2["written"] == 154
    assert await _count("creative_scene_prompt") == 154

    rows = await crud.list_creative_scene_prompts(cluster="Home & Living")
    assert rows
    assert all(svc.LIBRARY_SOURCE in (row.get("provenance") or "") for row in rows)

    # No Product Truth / snapshot / Copy Set mutation.
    assert await _count("product") == products_before
    assert await _count("product_intelligence_snapshot") == snap_before
    assert await _count("copy_set") == copy_before


@pytest.mark.asyncio
async def test_recommend_for_category_returns_templates_for_covered_cluster():
    result = await svc.recommend_scene_prompts_for_category("Home & Living")
    assert result["cluster"] == "Home & Living"
    assert result["cluster_source"] == "EXACT"
    assert result["template_count"] >= 3
    assert result["cluster_has_templates"] is True
    assert result["global_config"]["style_suffix"]
    # placeholders preserved in the returned payload
    assert all("[AVATAR]" in t["full_prompt_template"] for t in result["templates"])


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
    r_imp = await svc.recommend_scene_prompts_for_product(imported["id"])
    r_man = await svc.recommend_scene_prompts_for_product(manual["id"])
    assert r_imp["cluster"] == "Home & Living" and r_imp["template_count"] >= 3
    assert r_man["cluster"] == "Beauty" and r_man["template_count"] >= 3
    assert r_imp["product_id"] == imported["id"]


@pytest.mark.asyncio
async def test_uncovered_cluster_returns_empty_without_crashing():
    # Pet Care is a canonical cluster with no IMAGE_PROMPTS templates.
    manual = await crud.create_product(
        source="MANUAL", raw_product_title="Dog Chew", product_display_name="Dog Chew",
        product_short_name="Chew", category="Pet Care",
    )
    result = await svc.recommend_scene_prompts_for_product(manual["id"])
    assert result["cluster"] == "Pet Care"
    assert result["template_count"] == 0
    assert result["cluster_has_templates"] is False
    assert result["templates"] == []


@pytest.mark.asyncio
async def test_unknown_category_falls_back_safely():
    result = await svc.recommend_scene_prompts_for_category("Totally Unknown Thing")
    # Deterministic fallback cluster (Home & Living) is a covered cluster.
    assert result["cluster"] == "Home & Living"
    assert result["cluster_source"] == "FALLBACK"
    assert result["template_count"] >= 1  # never crashes


@pytest.mark.asyncio
async def test_recommend_missing_product_raises():
    with pytest.raises(ValueError, match="PRODUCT_NOT_FOUND"):
        await svc.recommend_scene_prompts_for_product("does-not-exist")


def test_invariant_generation_services_do_not_reference_scene_prompt_library():
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
        assert "creative_scene_prompt_service" not in text
        assert "creative_scene_prompt_library" not in text
