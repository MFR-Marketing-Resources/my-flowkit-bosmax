"""Disposable-DB proof for the seven additive Storyboard Landbank V3 tables."""

from __future__ import annotations

import shutil
import sqlite3

import pytest

from agent.config import DB_PATH
from agent.db.schema import close_db, get_db, init_db
from agent.models.copy_blueprint_v2 import digest_evidence_text


V3_TABLES = {
    "angle_v3",
    "storyline_family_v3",
    "storyboard_component_v3",
    "copy_recipe_v3",
    "master_storyboard_v3",
    "duration_projection_v3",
    "review_event_v3",
}
# Macro Round 3 production-integration tables — previously DEFERRED, now present.
ROUND3_TABLES = {
    "materialization_link_v3",
    "production_copy_supply_manifest_v3",
    "manifest_item_v3",
    "landbank_usage_v3",
}
ROUND2_TABLES = {
    "v3_ai_authoring_run",
    "v3_human_approval_receipt",
}
V3_INDEXES = {
    "idx_angle_v3_product_status",
    "idx_angle_v3_truth",
    "idx_angle_v3_formula",
    "idx_angle_v3_digest",
    "idx_storyline_family_v3_product_status",
    "idx_storyline_family_v3_angle",
    "idx_storyline_family_v3_formula",
    "idx_storyline_family_v3_digest",
    "idx_storyboard_component_v3_product_status",
    "idx_storyboard_component_v3_angle_storyline",
    "idx_storyboard_component_v3_formula_stage",
    "idx_storyboard_component_v3_digest",
    "idx_copy_recipe_v3_product_status",
    "idx_copy_recipe_v3_formula",
    "idx_copy_recipe_v3_campaign",
    "idx_copy_recipe_v3_digest",
    "idx_master_storyboard_v3_product_status",
    "idx_master_storyboard_v3_recipe",
    "idx_master_storyboard_v3_angle_storyline",
    "idx_master_storyboard_v3_formula",
    "idx_master_storyboard_v3_digest",
    "idx_duration_projection_v3_master",
    "idx_duration_projection_v3_product_duration",
    "idx_duration_projection_v3_truth",
    "idx_duration_projection_v3_digest",
    "idx_review_event_v3_entity",
    "idx_review_event_v3_product",
    "idx_review_event_v3_digest",
}


async def _seed_truth(key: str):
    product_id = f"v3-product-{key}"
    snapshot_id = f"v3-snapshot-{key}"
    db = await get_db()
    await db.execute(
        "INSERT INTO product (id, raw_product_title, product_display_name, product_short_name) "
        "VALUES (?, ?, ?, ?)",
        (product_id, "V3 Synthetic Product", "V3 Synthetic Product", "V3 Product"),
    )
    await db.execute(
        "INSERT INTO product_intelligence_snapshot "
        "(snapshot_id, product_id, version, status, created_at, updated_at, approved_by, approved_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            snapshot_id,
            product_id,
            1,
            "APPROVED",
            "2026-08-17T00:00:00Z",
            "2026-08-17T00:00:00Z",
            "v3-test-owner",
            "2026-08-17T00:00:00Z",
        ),
    )
    evidence_text = "The synthetic product has a lightweight daily formula."
    await db.execute(
        "INSERT INTO copy_evidence_fact_v2 "
        "(product_id, snapshot_id, fact_id, fact_kind, canonical_text, text_digest, "
        "snapshot_version, snapshot_status, approved, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            product_id,
            snapshot_id,
            f"fact-{key}",
            "PRODUCT_ATTRIBUTE",
            evidence_text,
            digest_evidence_text(evidence_text),
            1,
            "APPROVED",
            1,
            "2026-08-17T00:00:00Z",
        ),
    )
    await db.commit()


def _angle_values(
    angle_id: str,
    product_id: str,
    snapshot_id: str,
    fact_id: str,
    revision: int = 1,
    status: str = "DRAFT",
) -> tuple:
    digest = "a" * 64 if revision == 1 else "b" * 64
    return (
        angle_id,
        revision,
        product_id,
        snapshot_id,
        1,
        "c" * 64,
        "A lightweight daily formula angle",
        '{"objective_ids":["objective-1"]}',
        '{"audience":["daily-routine"]}',
        f'["{fact_id}"]',
        "d" * 64,
        None,
        None,
        "synthetic-test",
        status,
        digest,
        angle_id if revision > 1 else None,
        revision - 1 if revision > 1 else None,
        "2026-08-17T00:00:00Z",
        "v3-test",
    )


async def _insert_angle(
    key: str,
    angle_id: str,
    revision: int = 1,
    status: str = "DRAFT",
):
    db = await get_db()
    await db.execute(
        "INSERT INTO angle_v3 ("
        "angle_id, revision, product_id, product_truth_snapshot_id, product_truth_snapshot_version, "
        "product_truth_snapshot_digest, definition, objective_compatibility_json, audience_compatibility_json, "
        "evidence_fact_ids_json, evidence_digest, formula_id, formula_version, source, status, angle_digest, "
        "supersedes_angle_id, supersedes_angle_revision, created_at, created_by"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        _angle_values(
            angle_id,
            f"v3-product-{key}",
            f"v3-snapshot-{key}",
            f"fact-{key}",
            revision,
            status,
        ),
    )
    await db.commit()


@pytest.mark.asyncio
async def test_v3_core_tables_indexes_and_deferred_tables_are_exact():
    assert DB_PATH.name.startswith("flowkit-pytest-")
    assert DB_PATH.name != "flow_agent.db"
    db = await get_db()
    table_cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = {row[0] for row in await table_cursor.fetchall()}
    assert V3_TABLES <= tables
    assert ROUND2_TABLES <= tables
    assert ROUND3_TABLES <= tables

    index_cursor = await db.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE '%_v3_%'"
    )
    indexes = {row[0] for row in await index_cursor.fetchall()}
    assert V3_INDEXES <= indexes
    expected_columns = {
        "storyboard_component_v3": {"objective_id", "formula_stage_keys_json", "stage_segments_json", "content_digest"},
        "copy_recipe_v3": {"campaign_key", "objective_id", "deterministic_seed", "config_digest"},
        "master_storyboard_v3": {"objective_id", "exact_stage_texts_json", "duplicate_fingerprint"},
        "duration_projection_v3": {
            "master_id",
            "target_duration_seconds",
            "wps_authority_digest",
            "stage_allocations_json",
            "stage_allocation_digest",
            "stage_allocation_receipt_json",
            "derivation_source",
            "authoring_run_id",
        },
    }
    for table, required_columns in expected_columns.items():
        cursor = await db.execute(f"PRAGMA table_info({table})")
        columns = {row[1] for row in await cursor.fetchall()}
        assert required_columns <= columns

    legacy_sql_before = {}
    for table in ("copy_set", "copy_component"):
        cursor = await db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        )
        legacy_sql_before[table] = (await cursor.fetchone())[0]

    await _seed_truth("tables")
    await _insert_angle("tables", "angle-v3-tables")
    await close_db()
    await init_db()
    await close_db()
    await init_db()
    db = await get_db()

    row = await (await db.execute(
        "SELECT product_id, definition, status FROM angle_v3 WHERE angle_id=? AND revision=?",
        ("angle-v3-tables", 1),
    )).fetchone()
    assert tuple(row) == ("v3-product-tables", "A lightweight daily formula angle", "DRAFT")
    product = await (await db.execute("SELECT id FROM product WHERE id='v3-product-tables'")).fetchone()
    assert tuple(product) == ("v3-product-tables",)
    for table, expected_sql in legacy_sql_before.items():
        current = await (await db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        )).fetchone()
        assert current[0] == expected_sql


@pytest.mark.asyncio
async def test_v3_constraints_immutability_append_only_and_revision_supersession():
    await _seed_truth("constraints")
    await _insert_angle("constraints", "angle-v3-constraints", status="APPROVED")
    db = await get_db()
    with pytest.raises(sqlite3.IntegrityError, match="ANGLE_V3_IMMUTABLE"):
        await db.execute(
            "UPDATE angle_v3 SET definition='edited in place' WHERE angle_id='angle-v3-constraints' AND revision=1"
        )
    await db.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="ANGLE_V3_IMMUTABLE"):
        await db.execute("DELETE FROM angle_v3 WHERE angle_id='angle-v3-constraints' AND revision=1")
    await db.rollback()

    for terminal_status in ("FROZEN", "REJECTED", "BLOCKED"):
        angle_id = f"angle-v3-{terminal_status.lower()}"
        await _insert_angle("constraints", angle_id, status=terminal_status)
        with pytest.raises(sqlite3.IntegrityError, match="ANGLE_V3_IMMUTABLE"):
            await db.execute(
                "UPDATE angle_v3 SET definition='terminal edit' WHERE angle_id=? AND revision=1",
                (angle_id,),
            )
        await db.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="ANGLE_V3_IMMUTABLE"):
            await db.execute(
                "DELETE FROM angle_v3 WHERE angle_id=? AND revision=1", (angle_id,)
            )
        await db.rollback()

    await _insert_angle("constraints", "angle-v3-constraints", revision=2, status="DRAFT")
    superseded = await (await db.execute(
        "SELECT supersedes_angle_id, supersedes_angle_revision FROM angle_v3 "
        "WHERE angle_id='angle-v3-constraints' AND revision=2"
    )).fetchone()
    assert tuple(superseded) == ("angle-v3-constraints", 1)

    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            "INSERT INTO angle_v3 (angle_id, revision, product_id, product_truth_snapshot_id, "
            "product_truth_snapshot_version, product_truth_snapshot_digest, definition, evidence_digest, "
            "source, status, angle_digest, created_at, created_by) VALUES "
            "('bad-angle', 1, 'v3-product-constraints', 'v3-snapshot-constraints', 1, 'short', 'bad', 'short', 'test', 'DRAFT', 'short', 'now', 'test')"
        )
    await db.rollback()
    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            "INSERT INTO angle_v3 (angle_id, revision, product_id, product_truth_snapshot_id, "
            "product_truth_snapshot_version, product_truth_snapshot_digest, definition, evidence_digest, "
            "source, status, angle_digest, created_at, created_by) VALUES "
            "('bad-status', 1, 'v3-product-constraints', 'v3-snapshot-constraints', 1, '" + "a" * 64 + "', 'bad', '" + "b" * 64 + "', 'test', 'NOT_A_STATUS', '" + "c" * 64 + "', 'now', 'test')"
        )
    await db.rollback()

    await db.execute(
        "INSERT INTO review_event_v3 (event_id, entity_type, entity_id, entity_revision, product_id, "
        "event_type, actor_id, source, payload_digest, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "event-v3-1",
            "ANGLE",
            "angle-v3-constraints",
            2,
            "v3-product-constraints",
            "CREATED",
            "v3-test",
            "synthetic-test",
            "e" * 64,
            "2026-08-17T00:00:00Z",
        ),
    )
    await db.commit()
    with pytest.raises(sqlite3.IntegrityError, match="REVIEW_EVENT_V3_APPEND_ONLY"):
        await db.execute("UPDATE review_event_v3 SET reason='changed' WHERE event_id='event-v3-1'")
    await db.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="REVIEW_EVENT_V3_APPEND_ONLY"):
        await db.execute("DELETE FROM review_event_v3 WHERE event_id='event-v3-1'")
    await db.rollback()


@pytest.mark.asyncio
async def test_disposable_clone_can_be_checked_and_discarded_without_touching_test_source(tmp_path):
    await _seed_truth("clone")
    await _insert_angle("clone", "angle-v3-clone")
    await close_db()
    clone_path = tmp_path / "v3-recovery-clone.db"
    shutil.copy2(DB_PATH, clone_path)
    with sqlite3.connect(clone_path) as clone:
        tables = {
            row[0]
            for row in clone.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert V3_TABLES <= tables
        for table in (
            "review_event_v3",
            "duration_projection_v3",
            "master_storyboard_v3",
            "copy_recipe_v3",
            "storyboard_component_v3",
            "storyline_family_v3",
            "angle_v3",
        ):
            clone.execute(f"DROP TABLE {table}")
        clone.commit()
        remaining = {
            row[0]
            for row in clone.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert not (V3_TABLES & remaining)
    assert DB_PATH.exists()
    await init_db()
    db = await get_db()
    count = await (await db.execute(
        "SELECT COUNT(*) FROM angle_v3 WHERE angle_id='angle-v3-clone'"
    )).fetchone()
    assert tuple(count) == (1,)


@pytest.mark.asyncio
async def test_round3_ledger_append_only_and_manifest_freeze_immutability():
    """Round 3 production-integration tables enforce append-only usage and
    freeze-immutable manifests, matching the V3 core immutability contract."""
    await _seed_truth("r3")
    db = await get_db()
    product_id = "v3-product-r3"

    # landbank_usage_v3 is strictly append-only.
    await db.execute(
        "INSERT INTO landbank_usage_v3 (usage_id, product_id, usage_type, created_at, created_by) "
        "VALUES (?, ?, ?, ?, ?)",
        ("usage-r3-1", product_id, "MANIFEST_SELECT", "2026-08-18T00:00:00Z", "v3-test"),
    )
    await db.commit()
    with pytest.raises(sqlite3.IntegrityError, match="LANDBANK_USAGE_V3_APPEND_ONLY"):
        await db.execute("UPDATE landbank_usage_v3 SET outcome='x' WHERE usage_id='usage-r3-1'")
    await db.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="LANDBANK_USAGE_V3_APPEND_ONLY"):
        await db.execute("DELETE FROM landbank_usage_v3 WHERE usage_id='usage-r3-1'")
    await db.rollback()
    with pytest.raises(sqlite3.IntegrityError):  # usage_type CHECK enum
        await db.execute(
            "INSERT INTO landbank_usage_v3 (usage_id, product_id, usage_type, created_at, created_by) "
            "VALUES ('usage-bad', ?, 'NOT_A_TYPE', 'now', 'v3-test')",
            (product_id,),
        )
    await db.rollback()

    # production_copy_supply_manifest_v3: DRAFT->BUILT->FROZEN allowed; frozen is
    # immutable; delete forbidden.
    await db.execute(
        "INSERT INTO production_copy_supply_manifest_v3 "
        "(manifest_id, revision, product_id, selection_policy_version, manifest_digest, created_at, created_by) "
        "VALUES ('man-r3', 1, ?, 'copy-supply-selection-v1', ?, '2026-08-18T00:00:00Z', 'v3-test')",
        (product_id, "a" * 64),
    )
    await db.commit()
    await db.execute(
        "UPDATE production_copy_supply_manifest_v3 SET status='BUILT' WHERE manifest_id='man-r3' AND revision=1"
    )
    await db.execute(
        "UPDATE production_copy_supply_manifest_v3 SET status='FROZEN' WHERE manifest_id='man-r3' AND revision=1"
    )
    await db.commit()
    with pytest.raises(sqlite3.IntegrityError, match="SUPPLY_MANIFEST_V3_FROZEN_IMMUTABLE"):
        await db.execute(
            "UPDATE production_copy_supply_manifest_v3 SET status='ALLOCATED' WHERE manifest_id='man-r3' AND revision=1"
        )
    await db.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="SUPPLY_MANIFEST_V3_APPEND_ONLY"):
        await db.execute(
            "DELETE FROM production_copy_supply_manifest_v3 WHERE manifest_id='man-r3' AND revision=1"
        )
    await db.rollback()

    # digest CHECK: manifest_digest must be 64 chars.
    with pytest.raises(sqlite3.IntegrityError):
        await db.execute(
            "INSERT INTO production_copy_supply_manifest_v3 "
            "(manifest_id, revision, product_id, selection_policy_version, manifest_digest, created_at, created_by) "
            "VALUES ('man-bad', 1, ?, 'copy-supply-selection-v1', 'short', 'now', 'v3-test')",
            (product_id,),
        )
    await db.rollback()
