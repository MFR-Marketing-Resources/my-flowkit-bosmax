from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts import product_catalog_decontamination as mission


def _create_disposable_db(path: Path, *, external_id: bool = True, variant_conflict: bool = False) -> tuple[list[dict[str, str]], list[str]]:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        PRAGMA foreign_keys=ON;
        CREATE TABLE product (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL DEFAULT 'MANUAL',
            source_url TEXT,
            tiktok_product_url TEXT,
            shop_name TEXT,
            raw_product_title TEXT NOT NULL,
            product_display_name TEXT NOT NULL,
            product_short_name TEXT NOT NULL,
            image_url TEXT,
            media_id TEXT,
            local_image_path TEXT,
            lifecycle_status TEXT NOT NULL DEFAULT 'ACTIVE',
            archived_reason TEXT,
            lifecycle_provenance TEXT
        );
        CREATE TABLE fastmoss_bulk_draft_status (
            reference_id TEXT PRIMARY KEY,
            committed_product_id TEXT,
            title TEXT
        );
        CREATE TABLE request_telemetry (
            request_id TEXT PRIMARY KEY,
            product_id TEXT,
            request_lineage_payload TEXT
        );
        CREATE TABLE product_treatment_factory_task (
            task_id TEXT PRIMARY KEY,
            product_id TEXT,
            status TEXT
        );
        CREATE TABLE product_intelligence_snapshot (
            snapshot_id TEXT PRIMARY KEY,
            product_id TEXT REFERENCES product(id) ON DELETE CASCADE,
            image_evidence_json TEXT
        );
        """
    )
    pairs: list[dict[str, str]] = []
    aliases: list[str] = []
    for index in range(48):
        canonical_id = f"canonical-{index:02d}"
        alias_id = f"alias-{index:02d}"
        platform_id = str(1000000000000000000 + index)
        canonical_title = f"Alpha product {index} 30ml"
        duplicate_title = canonical_title if not variant_conflict else f"Alpha product {index} 100ml"
        canonical_url = f"https://shop.example/product/{platform_id}"
        duplicate_url = canonical_url if external_id else f"https://shop.example/product/{int(platform_id) + 9000}"
        connection.execute(
            "INSERT INTO product (id, source_url, tiktok_product_url, shop_name, raw_product_title, product_display_name, product_short_name, image_url, lifecycle_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE')",
            (canonical_id, canonical_url, canonical_url, "Shop", canonical_title, canonical_title, canonical_title, f"https://img.example/{canonical_id}.jpg"),
        )
        connection.execute(
            "INSERT INTO product (id, source_url, tiktok_product_url, shop_name, raw_product_title, product_display_name, product_short_name, image_url, lifecycle_status, archived_reason, lifecycle_provenance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ARCHIVED', ?, ?)",
            (alias_id, duplicate_url, duplicate_url, "Shop", duplicate_title, duplicate_title, duplicate_title, f"https://img.example/{canonical_id}.jpg", mission.marker_for(canonical_id), "[\"pi13\"]"),
        )
        connection.execute(
            "INSERT INTO fastmoss_bulk_draft_status (reference_id, committed_product_id, title) VALUES (?, ?, ?)",
            (f"ref-{index:02d}", alias_id, duplicate_title),
        )
        connection.execute(
            "INSERT INTO request_telemetry (request_id, product_id, request_lineage_payload) VALUES (?, ?, ?)",
            (f"req-{index:02d}", alias_id, json.dumps({"product_id": alias_id, "lineage": "historical"})),
        )
        connection.execute(
            "INSERT INTO product_treatment_factory_task (task_id, product_id, status) VALUES (?, ?, 'STALE')",
            (f"task-{index:02d}", alias_id),
        )
        connection.execute(
            "INSERT INTO product_intelligence_snapshot (snapshot_id, product_id, image_evidence_json) VALUES (?, ?, ?)",
            (f"snapshot-{index:02d}", alias_id, json.dumps({"alias": alias_id})),
        )
        pairs.append({"product_id": alias_id, "canonical_id": canonical_id, "signals": {"platform_product_id": platform_id}})
        aliases.append(alias_id)
    connection.commit()
    connection.close()
    return pairs, aliases


def _write_historical(path: Path, pairs: list[dict[str, str]]) -> None:
    path.write_text(json.dumps({"summary": {"MERGE_PROVEN": len(pairs)}, "merge_proven": pairs}), encoding="utf-8")


def test_plan_apply_verify_and_second_apply_are_idempotent(tmp_path: Path):
    db_path = tmp_path / "flow_agent.db"
    evidence_dir = tmp_path / "evidence"
    pairs, aliases = _create_disposable_db(db_path)
    historical_path = tmp_path / "historical.json"
    _write_historical(historical_path, pairs)

    audit = mission.audit_database(db_path, evidence_dir=evidence_dir, historical_path=historical_path, media_root=tmp_path)
    assert audit["reproof"]["current_reproven_count"] == 48
    assert audit["reproof"]["failures"] == []
    assert audit["plan"]["cohort_digest"]
    c0_baseline_before = (evidence_dir / "c0-baseline.json").read_text(encoding="utf-8")

    result = mission.main([
        "--apply",
        "--authorize", mission.AUTHORIZATION_TOKEN,
        "--db", str(db_path),
        "--evidence-dir", str(evidence_dir),
        "--historical-evidence", str(historical_path),
        "--media-root", str(tmp_path),
        "--backup-path", str(tmp_path / "backup.db"),
    ])
    assert result == 0
    after_document = json.loads((evidence_dir / "purge-after.json").read_text(encoding="utf-8"))
    assert after_document["status"] == "APPLIED"
    assert after_document["exact_arithmetic"]["physical_deletes"] == 48
    assert after_document["canonical_survivor_deletes"] == 0
    assert after_document["tombstones_created"] == 48
    assert after_document["child_records_migrated"] == 48
    assert after_document["child_records_safely_retired"] == 48
    assert after_document["database"]["consistent_snapshot_sha256"]
    assert after_document["post_backup"]["readable"] is True

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM product").fetchone()[0] == 48
        assert connection.execute("SELECT COUNT(*) FROM product_catalog_alias_tombstone").fetchone()[0] == 48
        assert connection.execute("SELECT COUNT(*) FROM product_catalog_alias_tombstone_child").fetchone()[0] == 288
        assert connection.execute("SELECT COUNT(*) FROM fastmoss_bulk_draft_status WHERE committed_product_id LIKE 'alias-%'").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM request_telemetry WHERE product_id LIKE 'alias-%'").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM product_treatment_factory_task").fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    second = mission.apply_purge(
        db_path,
        plan=audit["plan"],
        dependency=audit["dependency"],
        evidence_dir=evidence_dir,
        backup_path=tmp_path / "backup-second.db",
    )
    assert second["status"] == "IDEMPOTENT_NOOP"
    assert second["physical_duplicate_deletes"] == 0

    assert mission.main([
        "--verify",
        "--db", str(db_path),
        "--evidence-dir", str(evidence_dir),
        "--historical-evidence", str(historical_path),
        "--media-root", str(tmp_path),
    ]) == 0
    assert (evidence_dir / "c0-baseline.json").read_text(encoding="utf-8") == c0_baseline_before


def test_title_only_similarity_does_not_authorize_purge(tmp_path: Path):
    db_path = tmp_path / "flow_agent.db"
    evidence_dir = tmp_path / "evidence"
    pairs, _ = _create_disposable_db(db_path, external_id=False)
    historical_path = tmp_path / "historical.json"
    _write_historical(historical_path, pairs)

    result = mission.main([
        "--plan",
        "--db", str(db_path),
        "--evidence-dir", str(evidence_dir),
        "--historical-evidence", str(historical_path),
        "--media-root", str(tmp_path),
    ])
    assert result == 2
    assert "PLATFORM_ID_DISAGREEMENT" in (evidence_dir / "merge-proven-48-reproof.json").read_text(encoding="utf-8")


def test_variant_conflict_does_not_authorize_purge(tmp_path: Path):
    db_path = tmp_path / "flow_agent.db"
    evidence_dir = tmp_path / "evidence"
    pairs, _ = _create_disposable_db(db_path, variant_conflict=True)
    historical_path = tmp_path / "historical.json"
    _write_historical(historical_path, pairs)

    result = mission.main([
        "--plan",
        "--db", str(db_path),
        "--evidence-dir", str(evidence_dir),
        "--historical-evidence", str(historical_path),
        "--media-root", str(tmp_path),
    ])
    assert result == 2
    assert mission.FAIL_VARIANT_AMBIGUITY in (evidence_dir / "merge-proven-48-reproof.json").read_text(encoding="utf-8")


def test_unknown_dependency_policy_blocks_plan(tmp_path: Path):
    db_path = tmp_path / "flow_agent.db"
    evidence_dir = tmp_path / "evidence"
    pairs, aliases = _create_disposable_db(db_path)
    connection = sqlite3.connect(db_path)
    connection.execute("CREATE TABLE unknown_product_consumer (id TEXT PRIMARY KEY, product_id TEXT)")
    connection.execute("INSERT INTO unknown_product_consumer VALUES ('u1', ?)", (aliases[0],))
    connection.commit()
    connection.close()
    historical_path = tmp_path / "historical.json"
    _write_historical(historical_path, pairs)

    result = mission.main([
        "--plan",
        "--db", str(db_path),
        "--evidence-dir", str(evidence_dir),
        "--historical-evidence", str(historical_path),
        "--media-root", str(tmp_path),
    ])
    assert result == 2
    dependency_text = (evidence_dir / "dependency-blast-radius.json").read_text(encoding="utf-8")
    assert "unknown_product_consumer" in dependency_text
    assert "PURGE_BLOCKED_HISTORY" in dependency_text


def test_cohort_digest_changes_when_pair_changes():
    first = [{"duplicate_product_id": "d1", "canonical_survivor_product_id": "c1", "platform_product_id": "1"}]
    second = [{"duplicate_product_id": "d1", "canonical_survivor_product_id": "c2", "platform_product_id": "1"}]
    assert mission.cohort_digest(first) != mission.cohort_digest(second)
