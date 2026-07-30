from __future__ import annotations

import shutil
import sqlite3

from agent.services import creative_supply_delta_service as delta


MISSION_ID = "BOSMAX-P7-DELTA-TEST"
RUN_ID = "csr-delta-test"


def _schema(path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE copy_component (
            component_id TEXT PRIMARY KEY,
            content TEXT,
            status TEXT
        );
        CREATE TABLE copy_set (
            copy_set_id TEXT PRIMARY KEY,
            product_id TEXT,
            status TEXT
        );
        CREATE TABLE creative_asset (
            asset_id TEXT PRIMARY KEY,
            generation_recipe_id TEXT,
            local_file_path TEXT,
            mode_a_metadata_handoff TEXT
        );
        CREATE TABLE creative_supply_run (
            run_id TEXT PRIMARY KEY,
            mission_id TEXT
        );
        CREATE TABLE creative_supply_task (
            task_id TEXT PRIMARY KEY,
            run_id TEXT
        );
        CREATE TABLE creative_supply_review_event (
            event_id TEXT PRIMARY KEY,
            run_id TEXT
        );
        INSERT INTO copy_component VALUES
            ('component-existing', 'before', 'REVIEW_REQUIRED');
        """
    )
    connection.commit()
    connection.close()


def test_delta_export_and_apply_is_bounded_hash_guarded_and_idempotent(tmp_path):
    baseline = tmp_path / "baseline.db"
    isolated = tmp_path / "isolated.db"
    _schema(baseline)
    shutil.copy2(baseline, isolated)
    anchor_source = tmp_path / "isolated-anchor.png"
    anchor_source.write_bytes(b"p7-anchor-pixels")
    connection = sqlite3.connect(isolated)
    connection.executescript(
        f"""
        UPDATE copy_component SET content='after',status='APPROVED'
        WHERE component_id='component-existing';
        INSERT INTO copy_component VALUES
            ('component-new', 'reviewed copy', 'APPROVED');
        INSERT INTO copy_set VALUES
            ('copy-new', 'product-1', 'COPY_APPROVED');
        INSERT INTO creative_asset VALUES
            ('asset-anchor', '{delta.ANCHOR_RECIPE}',
             '{str(anchor_source).replace("'", "''")}', '{{"review_state":"APPROVED"}}');
        INSERT INTO creative_supply_run VALUES ('{RUN_ID}', '{MISSION_ID}');
        INSERT INTO creative_supply_task VALUES ('task-1', '{RUN_ID}');
        INSERT INTO creative_supply_review_event VALUES ('event-1', '{RUN_ID}');
        """
    )
    connection.commit()
    connection.close()
    delta_path = tmp_path / "p7-delta.json"
    bundle = tmp_path / "bundle"

    exported = delta.export_delta(
        baseline_db=baseline,
        isolated_db=isolated,
        output_path=delta_path,
        asset_bundle_dir=bundle,
        run_id=RUN_ID,
        mission_id=MISSION_ID,
    )

    assert exported["operation_count"] == 7
    assert exported["table_counts"]["copy_component"] == 2
    assert exported["asset_files"]["asset-anchor"]["bytes"] == len(
        b"p7-anchor-pixels"
    )

    canonical_root = tmp_path / "canonical"
    canonical_root.mkdir()
    canonical_db = canonical_root / "flow_agent.db"
    shutil.copy2(baseline, canonical_db)
    applied = delta.apply_delta(
        canonical_db=canonical_db,
        delta_path=delta_path,
        asset_bundle_dir=bundle,
        canonical_runtime_dir=canonical_root,
        expected_mission_id=MISSION_ID,
    )

    assert applied["inserted"] == 6
    assert applied["updated"] == 1
    assert applied["integrity_check"] == "ok"
    connection = sqlite3.connect(canonical_db)
    assert connection.execute(
        "SELECT content,status FROM copy_component "
        "WHERE component_id='component-existing'"
    ).fetchone() == ("after", "APPROVED")
    anchor_path = connection.execute(
        "SELECT local_file_path FROM creative_asset "
        "WHERE asset_id='asset-anchor'"
    ).fetchone()[0]
    connection.close()
    assert anchor_path == str(
        canonical_root / ".local-agent" / "creative-assets" / "asset-anchor.png"
    )
    assert (canonical_root / ".local-agent" / "creative-assets" / "asset-anchor.png").read_bytes() == (
        b"p7-anchor-pixels"
    )

    repeated = delta.apply_delta(
        canonical_db=canonical_db,
        delta_path=delta_path,
        asset_bundle_dir=bundle,
        canonical_runtime_dir=canonical_root,
        expected_mission_id=MISSION_ID,
    )
    assert repeated["inserted"] == 0
    assert repeated["updated"] == 0
    assert repeated["idempotent"] == 7
