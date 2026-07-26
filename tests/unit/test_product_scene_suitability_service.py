"""Round 1 Product Scene Suitability Registry service contracts."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from agent.db import crud
from agent.services import creative_avatar_recommendation_service as avatar_svc
from agent.services import product_scene_suitability_service as svc
from agent.services import scene_context_registry


async def _count(table: str) -> int:
    db = await crud.get_db()
    cur = await db.execute(f"SELECT COUNT(*) FROM {table}")
    return (await cur.fetchone())[0]


@pytest.mark.asyncio
async def test_category_recommendation_returns_preview_templates_for_known_cluster():
    result = await svc.recommend_scene_suitability_for_category("Beauty & Personal Care")

    assert result["cluster"] == "Beauty"
    assert result["cluster_source"] == "EXACT"
    assert result["review_required"] is False
    assert result["template_count"] == len(result["recommendations"])
    assert result["template_count"] >= 1
    recommendation = result["recommendations"][0]
    assert set(recommendation) >= {
        "template_id", "source_category", "variant", "main_action", "setting",
        "notes", "status", "suitability_reason",
    }
    assert recommendation["status"] == "READ_ONLY_PREVIEW"
    assert "Canonical cluster 'Beauty'" in recommendation["suitability_reason"]


@pytest.mark.asyncio
async def test_product_recommendation_resolves_stored_product_category():
    product = await crud.create_product(
        source="MANUAL",
        raw_product_title="Hydrating Facial Serum",
        product_display_name="Hydrating Facial Serum",
        product_short_name="Facial Serum",
        category="Beauty & Personal Care",
    )

    result = await svc.recommend_scene_suitability_for_product(product["id"])

    assert result["product_id"] == product["id"]
    assert result["product_name"] == "Hydrating Facial Serum"
    assert result["category"] == "Beauty & Personal Care"
    assert result["cluster"] == "Beauty"
    assert result["template_count"] >= 1


@pytest.mark.asyncio
async def test_unknown_category_fails_closed_using_existing_resolver_behavior():
    result = await svc.recommend_scene_suitability_for_category("Unmapped Nebula Equipment")

    assert result["cluster"] is None
    assert result["cluster_source"] == "REVIEW_REQUIRED_UNKNOWN_CATEGORY"
    assert result["review_required"] is True
    assert result["template_count"] == 0
    assert result["recommendations"] == []


@pytest.mark.asyncio
async def test_all_canonical_clusters_have_at_least_one_recommendation():
    for cluster in avatar_svc.canonical_clusters():
        result = await svc.recommend_scene_suitability_for_category(cluster)
        assert result["cluster"] == cluster
        assert result["template_count"] >= 1, cluster


@pytest.mark.asyncio
async def test_placeholders_remain_unresolved_and_reasons_are_deterministic():
    first = await svc.recommend_scene_suitability_for_category("Pet Care")
    second = await svc.recommend_scene_suitability_for_category("Pet Care")

    assert first["recommendations"] == second["recommendations"]
    assert all("[AVATAR]" in r["full_prompt_template"] for r in first["recommendations"])
    assert all("[PRODUCT]" in r["full_prompt_template"] for r in first["recommendations"])


@pytest.mark.asyncio
async def test_suitability_queries_do_not_mutate_authority_or_runtime_state():
    product = await crud.create_product(
        source="MANUAL",
        raw_product_title="Read Only Desk Lamp",
        product_display_name="Read Only Desk Lamp",
        product_short_name="Desk Lamp",
        category="Home & Living",
    )
    tables = (
        "product", "product_intelligence_snapshot", "copy_set", "creative_asset",
        "generated_artifact", "creative_scene_prompt",
    )
    before = {table: await _count(table) for table in tables}
    pool_before = scene_context_registry.list_pool()
    pool_file = Path(__file__).resolve().parents[2] / "agent" / "authority" / "SCENE_CONTEXT_POOL.csv"
    pool_digest_before = hashlib.sha256(pool_file.read_bytes()).hexdigest()

    await svc.recommend_scene_suitability_for_category("Home & Living")
    await svc.recommend_scene_suitability_for_product(product["id"])

    assert {table: await _count(table) for table in tables} == before
    assert scene_context_registry.list_pool() == pool_before
    assert hashlib.sha256(pool_file.read_bytes()).hexdigest() == pool_digest_before


@pytest.mark.asyncio
async def test_missing_product_raises_without_writing():
    with pytest.raises(ValueError, match="PRODUCT_NOT_FOUND"):
        await svc.recommend_scene_suitability_for_product("does-not-exist")


def test_no_generation_services_import_the_suitability_registry():
    repo_root = Path(__file__).resolve().parents[2]
    generation_files = (
        "agent/services/canonical_prompt_compiler.py",
        "agent/services/ai_copy_assist_service.py",
        "agent/services/copy_grounding_service.py",
        "agent/services/copy_binding_service.py",
        "agent/services/workspace_execution_package_service.py",
    )
    for rel in generation_files:
        assert "product_scene_suitability_service" not in (repo_root / rel).read_text(encoding="utf-8")
