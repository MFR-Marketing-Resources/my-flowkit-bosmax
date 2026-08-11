from __future__ import annotations

import pytest

from agent.db import crud
from agent.db.schema import get_db
from agent.services.copywriting_taxonomy_service import (
    SEED_CONFIRMATION,
    get_copywriting_taxonomy_rollup,
    list_copywriting_taxonomy_entries,
    load_authority_payload,
    load_authority_records,
    resolve_product_taxonomy_record,
    seed_copywriting_taxonomy_registry,
)


def test_committed_authority_snapshot_is_complete() -> None:
    payload = load_authority_payload()
    records = load_authority_records()

    assert payload["schema_version"] == "copywriting-taxonomy-v1"
    assert payload["record_count"] == 313
    assert len(records) == 313
    assert len({record["product_type_code"] for record in records}) == 313
    assert all(record["copywriting_angle"] for record in records)


@pytest.mark.asyncio
async def test_seed_is_additive_idempotent_and_rolls_up() -> None:
    product = await crud.create_product(
        "Unchanged product",
        source="MANUAL",
        category="Beauty & Personal Care",
        subcategory="Fragrance",
        type="Body Mist",
    )
    before = await crud.get_product(product["id"])

    plan = await seed_copywriting_taxonomy_registry(dry_run=True)
    assert plan["seed_count"] == 313
    assert plan["planned_insert_count"] == 313
    assert plan["planned_update_count"] == 0
    assert plan["mutation_performed"] is False
    assert plan["confirmation_required"] == SEED_CONFIRMATION

    db = await get_db()
    count_cursor = await db.execute(
        "SELECT COUNT(*) AS count FROM copywriting_taxonomy_registry"
    )
    assert (await count_cursor.fetchone())["count"] == 0

    applied = await seed_copywriting_taxonomy_registry(
        dry_run=False,
        confirm_apply=SEED_CONFIRMATION,
    )
    assert applied["seed_count"] == 313
    assert applied["planned_insert_count"] == 313
    assert applied["mutation_performed"] is True
    assert applied["active_count"] == 313
    assert applied["review_required_count"] == 0

    rollup = await get_copywriting_taxonomy_rollup()
    assert rollup["total_product_types"] == 313
    assert rollup["cluster_count"] == 54
    assert rollup["category_count"] == 18
    assert rollup["subcategory_count"] == 168
    assert rollup["type_count"] == 312
    assert rollup["angle_count"] == 295
    assert len(rollup["clusters"]) == 54

    filtered = await list_copywriting_taxonomy_entries(
        cluster_name="Toys & Hobbies",
        query="sticker",
        limit=10,
    )
    assert filtered["total"] >= 1
    assert all(item["cluster_name"] == "Toys & Hobbies" for item in filtered["items"])
    assert any(item["product_type_code"] == "3d_sticker_book" for item in filtered["items"])

    second_plan = await seed_copywriting_taxonomy_registry(dry_run=True)
    assert second_plan["planned_insert_count"] == 0
    assert second_plan["planned_update_count"] == 0
    assert second_plan["unchanged_count"] == 313

    after = await crud.get_product(product["id"])
    assert after == before


@pytest.mark.asyncio
async def test_product_resolver_is_exact_and_fails_closed_on_ambiguity() -> None:
    await seed_copywriting_taxonomy_registry(
        dry_run=False,
        confirm_apply=SEED_CONFIRMATION,
    )
    record = load_authority_records()[0]

    exact_code = await resolve_product_taxonomy_record(
        {
            "id": "product-code",
            "product_display_name": "Code product",
            "copywriting_product_type_code": record["product_type_code"],
            "copywriting_cluster": record["cluster_name"],
        }
    )
    assert exact_code["match_status"] == "EXACT_CODE"
    assert exact_code["match"]["product_type_code"] == record["product_type_code"]

    conflicting_code = await resolve_product_taxonomy_record(
        {
            "id": "product-conflicting-code",
            "product_display_name": "Conflicting code product",
            "copywriting_product_type_code": record["product_type_code"],
            "copywriting_cluster": "wrong-cluster",
            "category": record["category"],
            "subcategory": record["subcategory"],
            "type": record["type"],
        }
    )
    assert conflicting_code["match_status"] == "UNMATCHED"
    assert conflicting_code["matched_by"] == "PRODUCT_TYPE_CODE"

    exact_fields = await resolve_product_taxonomy_record(
        {
            "id": "product-fields",
            "product_display_name": "Field product",
            "category": record["category"],
            "subcategory": record["subcategory"],
            "type": record["type"],
        }
    )
    assert exact_fields["match_status"] == "EXACT_TAXONOMY"
    assert exact_fields["matched_by"] == "CATEGORY_SUBCATEGORY_TYPE"

    ambiguous = await resolve_product_taxonomy_record(
        {
            "id": "product-ambiguous",
            "product_display_name": "Ambiguous soap",
            "category": "Beauty & Personal Care",
            "subcategory": "Facial Cleansing",
            "type": "Brightening Facial Soap",
        }
    )
    assert ambiguous["match_status"] == "AMBIGUOUS"
    assert {item["product_type_code"] for item in ambiguous["candidates"]} == {
        "brightening_facial_soap",
        "facial_cleansing_soap",
    }

    unmatched = await resolve_product_taxonomy_record(
        {
            "id": "product-unmatched",
            "product_display_name": "Unmapped product",
            "category": "not-in-registry",
            "subcategory": "not-in-registry",
            "type": "not-in-registry",
        }
    )
    assert unmatched["match_status"] == "UNMATCHED"
    assert unmatched["match"] is None
