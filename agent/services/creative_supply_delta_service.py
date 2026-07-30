"""Bounded P7 isolated-to-canonical database delta transfer.

Only P7 supply authority rows and their reviewed copy/asset dependencies are
eligible. The importer is additive/update-only, row-hash guarded, transactional
and idempotent; it never replaces the canonical database file.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from agent.models.creative_production import P58_COHORT_SHA256

DELTA_VERSION = "P7_CANONICAL_DELTA_V1"
TABLE_SPECS = (
    ("copy_component", "component_id", None),
    ("copy_set", "copy_set_id", None),
    ("creative_asset", "asset_id", None),
    ("creative_supply_run", "run_id", "run_id"),
    ("creative_supply_task", "task_id", "run_id"),
    ("creative_supply_review_event", "event_id", "run_id"),
)
ANCHOR_RECIPE = "P7_PRODUCT_ONLY_F2V_ANCHOR_916"


class CreativeSupplyDeltaError(ValueError):
    pass


def _stable_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _row_sha256(row: dict[str, Any]) -> str:
    return hashlib.sha256(_stable_json(row).encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        is not None
    )


def _rows_by_key(
    connection: sqlite3.Connection,
    table: str,
    primary_key: str,
    *,
    filter_column: str | None = None,
    filter_value: str | None = None,
) -> dict[str, dict[str, Any]]:
    if not _table_exists(connection, table):
        return {}
    query = f'SELECT * FROM "{table}"'
    parameters: tuple[Any, ...] = ()
    if filter_column:
        query += f' WHERE "{filter_column}"=?'
        parameters = (filter_value,)
    query += f' ORDER BY "{primary_key}"'
    rows = connection.execute(query, parameters).fetchall()
    return {str(row[primary_key]): dict(row) for row in rows}


def export_delta(
    *,
    baseline_db: Path,
    isolated_db: Path,
    output_path: Path,
    asset_bundle_dir: Path,
    run_id: str,
    mission_id: str,
) -> dict[str, Any]:
    baseline_db = baseline_db.resolve()
    isolated_db = isolated_db.resolve()
    if baseline_db == isolated_db:
        raise CreativeSupplyDeltaError("BASELINE_AND_ISOLATED_DB_MUST_DIFFER")
    if not baseline_db.is_file() or not isolated_db.is_file():
        raise CreativeSupplyDeltaError("DELTA_DATABASE_NOT_FOUND")
    baseline = sqlite3.connect(baseline_db)
    target = sqlite3.connect(isolated_db)
    baseline.row_factory = sqlite3.Row
    target.row_factory = sqlite3.Row
    operations: list[dict[str, Any]] = []
    try:
        run = target.execute(
            "SELECT mission_id FROM creative_supply_run WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if run is None or str(run["mission_id"]) != mission_id:
            raise CreativeSupplyDeltaError("P7_RUN_MISSION_MISMATCH")
        for table, primary_key, filter_column in TABLE_SPECS:
            before = _rows_by_key(
                baseline,
                table,
                primary_key,
                filter_column=filter_column,
                filter_value=run_id,
            )
            after = _rows_by_key(
                target,
                table,
                primary_key,
                filter_column=filter_column,
                filter_value=run_id,
            )
            for key, row in after.items():
                prior = before.get(key)
                if prior is None:
                    operations.append(
                        {
                            "table": table,
                            "primary_key": primary_key,
                            "key": key,
                            "operation": "INSERT",
                            "row": row,
                            "row_sha256": _row_sha256(row),
                        }
                    )
                elif prior != row:
                    operations.append(
                        {
                            "table": table,
                            "primary_key": primary_key,
                            "key": key,
                            "operation": "UPDATE",
                            "expected_before_sha256": _row_sha256(prior),
                            "row": row,
                            "row_sha256": _row_sha256(row),
                        }
                    )
    finally:
        baseline.close()
        target.close()

    asset_bundle_dir.mkdir(parents=True, exist_ok=True)
    asset_files: dict[str, dict[str, Any]] = {}
    for operation in operations:
        if operation["table"] != "creative_asset":
            continue
        row = operation["row"]
        if str(row.get("generation_recipe_id") or "") != ANCHOR_RECIPE:
            continue
        source_path = Path(str(row.get("local_file_path") or "")).resolve()
        if not source_path.is_file():
            raise CreativeSupplyDeltaError(
                f"ANCHOR_ASSET_FILE_MISSING:{operation['key']}"
            )
        file_name = f"{operation['key']}{source_path.suffix.lower() or '.png'}"
        bundled_path = asset_bundle_dir / file_name
        shutil.copy2(source_path, bundled_path)
        digest = _file_sha256(bundled_path)
        asset_files[str(operation["key"])] = {
            "file_name": file_name,
            "sha256": digest,
            "bytes": bundled_path.stat().st_size,
        }

    table_counts: dict[str, int] = {}
    for operation in operations:
        table = str(operation["table"])
        table_counts[table] = table_counts.get(table, 0) + 1
    manifest: dict[str, Any] = {
        "delta_version": DELTA_VERSION,
        "mission_id": mission_id,
        "run_id": run_id,
        "p58_cohort_sha256": P58_COHORT_SHA256,
        "baseline_db_sha256": _file_sha256(baseline_db),
        "isolated_db_sha256": _file_sha256(isolated_db),
        "operation_count": len(operations),
        "table_counts": table_counts,
        "asset_files": asset_files,
        "operations": operations,
    }
    manifest["manifest_sha256"] = hashlib.sha256(
        _stable_json(manifest).encode("utf-8")
    ).hexdigest()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "output_path": str(output_path),
        "manifest_sha256": manifest["manifest_sha256"],
        "operation_count": len(operations),
        "table_counts": table_counts,
        "asset_files": asset_files,
    }


def apply_delta(
    *,
    canonical_db: Path,
    delta_path: Path,
    asset_bundle_dir: Path,
    canonical_runtime_dir: Path,
    expected_mission_id: str,
) -> dict[str, Any]:
    canonical_db = canonical_db.resolve()
    canonical_runtime_dir = canonical_runtime_dir.resolve()
    if canonical_db != canonical_runtime_dir / "flow_agent.db":
        raise CreativeSupplyDeltaError("CANONICAL_DB_BINDING_MISMATCH")
    manifest = json.loads(delta_path.read_text(encoding="utf-8"))
    expected_manifest_sha = str(manifest.pop("manifest_sha256", ""))
    actual_manifest_sha = hashlib.sha256(
        _stable_json(manifest).encode("utf-8")
    ).hexdigest()
    manifest["manifest_sha256"] = expected_manifest_sha
    if expected_manifest_sha != actual_manifest_sha:
        raise CreativeSupplyDeltaError("DELTA_MANIFEST_HASH_MISMATCH")
    if manifest.get("delta_version") != DELTA_VERSION:
        raise CreativeSupplyDeltaError("DELTA_VERSION_UNSUPPORTED")
    if manifest.get("mission_id") != expected_mission_id:
        raise CreativeSupplyDeltaError("DELTA_MISSION_MISMATCH")
    if manifest.get("p58_cohort_sha256") != P58_COHORT_SHA256:
        raise CreativeSupplyDeltaError("DELTA_COHORT_AUTHORITY_MISMATCH")
    operations = manifest.get("operations")
    if not isinstance(operations, list):
        raise CreativeSupplyDeltaError("DELTA_OPERATIONS_INVALID")
    allowed = {(table, primary_key) for table, primary_key, _ in TABLE_SPECS}
    for operation in operations:
        if (operation.get("table"), operation.get("primary_key")) not in allowed:
            raise CreativeSupplyDeltaError("DELTA_TABLE_OUT_OF_SCOPE")
        if _row_sha256(operation.get("row") or {}) != operation.get("row_sha256"):
            raise CreativeSupplyDeltaError("DELTA_ROW_HASH_MISMATCH")

    destination_dir = canonical_runtime_dir / ".local-agent" / "creative-assets"
    destination_dir.mkdir(parents=True, exist_ok=True)
    copied_assets: list[dict[str, Any]] = []
    asset_files = manifest.get("asset_files") or {}
    for asset_id, metadata in asset_files.items():
        source = (asset_bundle_dir / str(metadata["file_name"])).resolve()
        if not source.is_file() or _file_sha256(source) != metadata["sha256"]:
            raise CreativeSupplyDeltaError(f"DELTA_ASSET_HASH_MISMATCH:{asset_id}")
        destination = destination_dir / str(metadata["file_name"])
        if destination.exists() and _file_sha256(destination) != metadata["sha256"]:
            raise CreativeSupplyDeltaError(
                f"CANONICAL_ASSET_COLLISION:{asset_id}"
            )
        if not destination.exists():
            shutil.copy2(source, destination)
        copied_assets.append(
            {
                "asset_id": asset_id,
                "path": str(destination),
                "sha256": metadata["sha256"],
            }
        )

    connection = sqlite3.connect(canonical_db)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    inserted = 0
    updated = 0
    idempotent = 0
    try:
        connection.execute("BEGIN IMMEDIATE")
        for operation in operations:
            table = str(operation["table"])
            primary_key = str(operation["primary_key"])
            key = str(operation["key"])
            row = dict(operation["row"])
            if table == "creative_asset" and key in asset_files:
                row["local_file_path"] = str(
                    destination_dir / str(asset_files[key]["file_name"])
                )
                operation_sha = _row_sha256(row)
            else:
                operation_sha = str(operation["row_sha256"])
            current_row = connection.execute(
                f'SELECT * FROM "{table}" WHERE "{primary_key}"=?',
                (key,),
            ).fetchone()
            current = dict(current_row) if current_row is not None else None
            if current is not None and _row_sha256(current) == operation_sha:
                idempotent += 1
                continue
            if operation["operation"] == "INSERT":
                if current is not None:
                    raise CreativeSupplyDeltaError(
                        f"CANONICAL_INSERT_COLLISION:{table}:{key}"
                    )
                columns = list(row)
                placeholders = ",".join("?" for _ in columns)
                quoted_columns = ",".join(f'"{column}"' for column in columns)
                connection.execute(
                    f'INSERT INTO "{table}" ({quoted_columns}) '
                    f"VALUES ({placeholders})",
                    tuple(row[column] for column in columns),
                )
                inserted += 1
                continue
            if current is None:
                raise CreativeSupplyDeltaError(
                    f"CANONICAL_UPDATE_TARGET_MISSING:{table}:{key}"
                )
            expected_before_sha = str(operation.get("expected_before_sha256") or "")
            if _row_sha256(current) != expected_before_sha:
                raise CreativeSupplyDeltaError(
                    f"CANONICAL_ROW_DRIFT:{table}:{key}"
                )
            update_columns = [column for column in row if column != primary_key]
            assignments = ",".join(f'"{column}"=?' for column in update_columns)
            connection.execute(
                f'UPDATE "{table}" SET {assignments} WHERE "{primary_key}"=?',
                tuple(row[column] for column in update_columns) + (key,),
            )
            updated += 1
        connection.commit()
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            raise CreativeSupplyDeltaError(f"CANONICAL_INTEGRITY_FAILED:{integrity}")
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return {
        "canonical_db": str(canonical_db),
        "canonical_db_sha256": _file_sha256(canonical_db),
        "manifest_sha256": expected_manifest_sha,
        "inserted": inserted,
        "updated": updated,
        "idempotent": idempotent,
        "integrity_check": "ok",
        "copied_assets": copied_assets,
    }
