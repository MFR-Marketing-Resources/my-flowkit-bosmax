"""P7.5-B additive schema, retention, and database constraint evidence."""

import sqlite3

import pytest

from agent.db import creative_treatment_crud as treatment_crud
from agent.db.schema import close_db, get_db, init_db


SHA_A = "a" * 64
SHA_B = "b" * 64


async def _seed_authority() -> None:
    db = await get_db()
    await db.execute(
        """
        INSERT OR IGNORE INTO product (
            id, raw_product_title, product_display_name, product_short_name
        ) VALUES ('product-p75b', 'Rempah', 'Rempah', 'Rempah')
        """
    )
    await db.execute(
        """
        INSERT OR IGNORE INTO copy_set (
            copy_set_id, product_id, angle, hook, status
        ) VALUES ('copy-p75b', 'product-p75b', 'Aroma', 'Harum rempah.', 'COPY_APPROVED')
        """
    )
    await db.execute(
        """
        INSERT OR IGNORE INTO product_intelligence_snapshot (
            snapshot_id, product_id, version, status, created_at, updated_at
        ) VALUES (
            'truth-p75b', 'product-p75b', 1, 'APPROVED',
            '2026-07-30T00:00:00Z', '2026-07-30T00:00:00Z'
        )
        """
    )
    await db.commit()


def _treatment_row(
    group_id: str | None = None,
    *,
    treatment_id: str = "treatment-p75b",
) -> dict[str, object]:
    return {
        "treatment_id": treatment_id,
        "product_id": "product-p75b",
        "status": "DRAFT",
        "format": "PGC",
        "generation_mode": "SINGLE",
        "duration_seconds": 8,
        "product_truth_snapshot_id": "truth-p75b",
        "product_truth_sha256": SHA_A,
        "copy_set_id": "copy-p75b",
        "copy_set_sha256": SHA_A,
        "creative_selection_id": "selection-p75b",
        "creative_selection_sha256": SHA_A,
        "scene_strategy_id": "SPICE_SEASONING",
        "scene_strategy_sha256": SHA_A,
        "content_angle": "Aroma",
        "dialogue_text": "Harum rempah.",
        "dialogue_sha256": SHA_A,
        "avatar_code": None,
        "avatar_sha256": None,
        "wardrobe_text": None,
        "wardrobe_sha256": None,
        "scene_template_id": None,
        "scene_template_sha256": None,
        "camera_preset_code": None,
        "camera_preset_sha256": None,
        "asset_bindings_json": "[]",
        "action_sequence_json": "[]",
        "shot_grammar_json": "[]",
        "compatibility_profile_json": "{}",
        "visual_fingerprint_sha256": SHA_A,
        "variation_group_id": group_id,
        "variation_ordinal": 1 if group_id else None,
        "treatment_sha256": SHA_A,
        "supersedes_treatment_id": None,
        "created_by": "migration-test",
    }


@pytest.mark.asyncio
async def test_additive_migration_is_idempotent_and_retains_treatment_rows():
    await _seed_authority()
    await treatment_crud.create_variation_group(
        {
            "group_id": "group-p75b",
            "product_id": "product-p75b",
            "copy_set_id": "copy-p75b",
            "dialogue_sha256": SHA_A,
            "status": "DRAFT",
            "created_by": "migration-test",
        },
    )
    await treatment_crud.create_treatment(_treatment_row("group-p75b"))
    await close_db()
    await init_db()
    await close_db()
    await init_db()

    treatment = await treatment_crud.get_treatment("treatment-p75b")
    group = await treatment_crud.get_variation_group("group-p75b")
    assert treatment is not None
    assert treatment["variation_ordinal"] == 1
    assert group is not None
    assert group["dialogue_sha256"] == SHA_A


@pytest.mark.asyncio
async def test_required_tables_indexes_and_hash_triggers_exist():
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT type, name
        FROM sqlite_master
        WHERE name LIKE '%creative_treatment%'
           OR name LIKE '%creative_variation_group%'
        """
    )
    objects = {(row[0], row[1]) for row in await cursor.fetchall()}
    assert {
        ("table", "creative_treatment"),
        ("table", "creative_treatment_audit_event"),
        ("table", "creative_variation_group"),
        ("index", "idx_creative_treatment_product_status"),
        ("index", "idx_creative_treatment_group"),
        ("index", "idx_creative_treatment_dialogue"),
        ("index", "idx_creative_variation_group_product_status"),
        ("trigger", "trg_creative_treatment_approved_hash_immutable"),
        ("trigger", "trg_creative_treatment_approved_content_immutable"),
        ("trigger", "trg_creative_variation_group_approved_hash_immutable"),
    } <= objects


@pytest.mark.asyncio
async def test_generation_modes_variation_pair_and_approved_hash_are_enforced():
    await _seed_authority()
    db = await get_db()

    extend_id = "treatment-p75b-extend"
    extend_row = _treatment_row(treatment_id=extend_id)
    extend_row["generation_mode"] = "EXTEND"
    await treatment_crud.create_treatment(extend_row)
    persisted_extend = await treatment_crud.get_treatment(extend_id)
    assert persisted_extend is not None
    assert persisted_extend["generation_mode"] == "EXTEND"
    assert persisted_extend["segment_plan_json"] == "[]"

    invalid_row = _treatment_row(treatment_id="treatment-p75b-invalid-mode")
    invalid_row["generation_mode"] = "BATCH"
    with pytest.raises(sqlite3.IntegrityError):
        await treatment_crud.create_treatment(invalid_row)

    treatment_id = "treatment-p75b-constraints"
    row = _treatment_row(treatment_id=treatment_id)
    row["variation_ordinal"] = 1
    with pytest.raises(sqlite3.IntegrityError):
        await treatment_crud.create_treatment(row)

    await treatment_crud.create_treatment(
        _treatment_row(treatment_id=treatment_id),
    )
    await db.execute(
        "UPDATE creative_treatment SET status='APPROVED' WHERE treatment_id=?",
        (treatment_id,),
    )
    await db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            "UPDATE creative_treatment SET treatment_sha256=? WHERE treatment_id=?",
            (SHA_B, treatment_id),
        )
    await db.rollback()
