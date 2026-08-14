from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "migrate_copy_register_v2_only.py"
SPEC = importlib.util.spec_from_file_location("copy_v2_cutover_migration", SCRIPT)
assert SPEC and SPEC.loader
migration = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = migration
SPEC.loader.exec_module(migration)


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE product (id TEXT PRIMARY KEY);
CREATE TABLE copy_blueprint_v2 (blueprint_id TEXT PRIMARY KEY);
CREATE TABLE copy_angle_candidate_v2 (angle_id TEXT PRIMARY KEY);
CREATE TABLE copy_evidence_fact_v2 (fact_id TEXT PRIMARY KEY);
CREATE TABLE copy_execution_binding_v2 (binding_id TEXT PRIMARY KEY);
CREATE TABLE copy_execution_authority_v2 (
    product_id TEXT NOT NULL,
    lane TEXT NOT NULL,
    binding_id TEXT NOT NULL,
    PRIMARY KEY (product_id, lane)
);
CREATE TABLE copy_set (
    copy_set_id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES product(id),
    hook TEXT NOT NULL DEFAULT ''
);
CREATE TABLE copy_component (
    component_id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT ''
);
CREATE TABLE poster_copy_set (
    poster_copy_set_id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL,
    primary_message TEXT NOT NULL DEFAULT ''
);
CREATE TABLE creative_variation_group (
    group_id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES product(id),
    copy_set_id TEXT NOT NULL REFERENCES copy_set(copy_set_id) ON DELETE RESTRICT,
    supersedes_group_id TEXT REFERENCES creative_variation_group(group_id)
);
CREATE INDEX idx_test_variation_copy ON creative_variation_group(copy_set_id);
CREATE TABLE creative_treatment (
    treatment_id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES product(id),
    copy_set_id TEXT NOT NULL REFERENCES copy_set(copy_set_id) ON DELETE RESTRICT,
    variation_group_id TEXT REFERENCES creative_variation_group(group_id),
    supersedes_treatment_id TEXT REFERENCES creative_treatment(treatment_id)
);
CREATE INDEX idx_test_treatment_copy ON creative_treatment(copy_set_id);
CREATE TRIGGER trg_test_treatment_immutable
BEFORE UPDATE ON creative_treatment
BEGIN SELECT RAISE(ABORT, 'IMMUTABLE'); END;
CREATE TABLE creative_supply_review_event (
    event_id TEXT PRIMARY KEY,
    component_id TEXT NOT NULL REFERENCES copy_component(component_id) ON DELETE RESTRICT,
    product_id TEXT NOT NULL REFERENCES product(id)
);
CREATE TABLE content_combination (
    combination_id TEXT PRIMARY KEY,
    copy_set_id TEXT
);
CREATE TABLE poster_deliverable (
    poster_deliverable_id TEXT PRIMARY KEY,
    poster_copy_set_id TEXT NOT NULL DEFAULT ''
);
"""


def _fixture(path: Path, *, unexpected_reference: bool = False) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(SCHEMA)
        connection.execute("INSERT INTO product(id) VALUES ('p1')")
        connection.execute(
            "INSERT INTO copy_set(copy_set_id, product_id, hook) VALUES ('cs1','p1','hook')"
        )
        connection.execute(
            "INSERT INTO copy_component(component_id, product_id, content) VALUES ('cc1','p1','body')"
        )
        connection.execute(
            "INSERT INTO poster_copy_set(poster_copy_set_id, product_id, primary_message) "
            "VALUES ('pcs1','p1','headline')"
        )
        connection.execute(
            "INSERT INTO creative_variation_group(group_id, product_id, copy_set_id) "
            "VALUES ('vg1','p1','cs1')"
        )
        connection.execute(
            "INSERT INTO creative_treatment(treatment_id, product_id, copy_set_id, variation_group_id) "
            "VALUES ('ct1','p1','cs1','vg1')"
        )
        connection.execute(
            "INSERT INTO creative_supply_review_event(event_id, component_id, product_id) "
            "VALUES ('ev1','cc1','p1')"
        )
        connection.execute(
            "INSERT INTO content_combination(combination_id, copy_set_id) VALUES ('comb1','cs1')"
        )
        connection.execute(
            "INSERT INTO poster_deliverable(poster_deliverable_id, poster_copy_set_id) "
            "VALUES ('pd1','pcs1')"
        )
        connection.execute("INSERT INTO copy_blueprint_v2 VALUES ('bp1')")
        connection.execute("INSERT INTO copy_angle_candidate_v2 VALUES ('angle1')")
        connection.execute("INSERT INTO copy_evidence_fact_v2 VALUES ('fact1')")
        connection.execute("INSERT INTO copy_execution_binding_v2 VALUES ('bind1')")
        connection.execute(
            "INSERT INTO copy_execution_authority_v2 VALUES ('p1','T2V','bind1')"
        )
        if unexpected_reference:
            connection.execute(
                "CREATE TABLE accidental_consumer(id TEXT PRIMARY KEY, copy_set_id TEXT)"
            )
        connection.commit()
    finally:
        connection.close()


def test_cutover_archives_every_row_retargets_history_and_locks_active_stores(
    tmp_path: Path,
) -> None:
    database = tmp_path / "cutover.db"
    _fixture(database)
    result = migration.perform_cutover(
        database,
        backup_path=tmp_path / "pre-cutover.db",
        backup_sha256="a" * 64,
    )

    assert result.before_counts == {
        "copy_set": 1,
        "copy_component": 1,
        "poster_copy_set": 1,
    }
    assert result.after_counts == {
        "copy_set": 0,
        "copy_component": 0,
        "poster_copy_set": 0,
    }
    assert sum(result.reference_counts.values()) == 5
    assert result.cleared_reference_counts == {
        "content_combination.copy_set_id": 1,
        "poster_deliverable.poster_copy_set_id": 1,
    }
    assert result.unresolved_active_reference_counts == {
        "content_combination.copy_set_id": 0,
        "poster_deliverable.poster_copy_set_id": 0,
    }
    assert result.integrity_check == "ok"
    assert result.foreign_key_violations == []

    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM legacy_copy_set_receipt"
        ).fetchone()[0] == 1
        archived = connection.execute(
            "SELECT row_json, row_sha256 FROM legacy_copy_set_receipt"
        ).fetchone()
        assert archived is not None
        assert json.loads(archived["row_json"])["hook"] == "hook"
        assert hashlib.sha256(archived["row_json"].encode()).hexdigest() == archived[
            "row_sha256"
        ]
        assert connection.execute(
            "SELECT COUNT(*) FROM creative_treatment"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM creative_supply_review_event"
        ).fetchone()[0] == 1
        treatment_targets = {
            row[2] for row in connection.execute("PRAGMA foreign_key_list(creative_treatment)")
        }
        event_targets = {
            row[2]
            for row in connection.execute(
                "PRAGMA foreign_key_list(creative_supply_review_event)"
            )
        }
        assert "legacy_copy_set_receipt" in treatment_targets
        assert "legacy_copy_component_receipt" in event_targets
        assert connection.execute(
            "SELECT copy_set_id FROM content_combination WHERE combination_id='comb1'"
        ).fetchone()[0] is None
        assert connection.execute(
            "SELECT poster_copy_set_id FROM poster_deliverable "
            "WHERE poster_deliverable_id='pd1'"
        ).fetchone()[0] == ""
        assert connection.execute(
            "SELECT COUNT(*) FROM legacy_copy_reference_receipt"
        ).fetchone()[0] == 5
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        with pytest.raises(sqlite3.IntegrityError, match="LEGACY_COPY_STORAGE_DISABLED"):
            connection.execute(
                "INSERT INTO copy_set(copy_set_id, product_id, hook) VALUES ('new','p1','x')"
            )
    finally:
        connection.close()


def test_cutover_fails_closed_when_an_unknown_legacy_reference_surface_appears(
    tmp_path: Path,
) -> None:
    database = tmp_path / "unexpected.db"
    _fixture(database, unexpected_reference=True)

    with pytest.raises(migration.CutoverError, match="LEGACY_REFERENCE_SURFACE_CHANGED"):
        migration.perform_cutover(
            database,
            backup_path=tmp_path / "pre-cutover.db",
            backup_sha256="b" * 64,
        )

    connection = sqlite3.connect(database)
    try:
        assert connection.execute("SELECT COUNT(*) FROM copy_set").fetchone()[0] == 1
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name='legacy_copy_set_receipt'"
            ).fetchone()[0]
            == 0
        )
    finally:
        connection.close()
