#!/usr/bin/env python3
"""P5.8 dry-run, transactional apply, idempotency, and evidence runner."""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path


MISSION_ID = "BOSMAX-P5.8-FINAL-CATALOG-AUTHORITY-P4-CLOSURE-20260729"
CANONICAL_CONFIRMATION = "APPLY_P58_TO_CANONICAL_AFTER_BACKUP_AND_QUEUE_PROOF"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _stable_json_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _backup_database(source: Path, destination: Path) -> dict[str, object]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(source)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
    finally:
        destination_connection.close()
        source_connection.close()
    connection = sqlite3.connect(destination)
    try:
        integrity = str(
            connection.execute("PRAGMA integrity_check").fetchone()[0]
        )
        quick_check = str(
            connection.execute("PRAGMA quick_check").fetchone()[0]
        )
        product_count = int(
            connection.execute("SELECT COUNT(*) FROM product").fetchone()[0]
        )
    finally:
        connection.close()
    return {
        "path": str(destination.resolve()),
        "sha256": _sha256(destination),
        "size_bytes": destination.stat().st_size,
        "integrity_check": integrity,
        "quick_check": quick_check,
        "product_count": product_count,
    }


def _database_checks(database_path: Path) -> dict[str, object]:
    connection = sqlite3.connect(database_path)
    try:
        return {
            "integrity_check": str(
                connection.execute("PRAGMA integrity_check").fetchone()[0]
            ),
            "quick_check": str(
                connection.execute("PRAGMA quick_check").fetchone()[0]
            ),
            "product_count": int(
                connection.execute("SELECT COUNT(*) FROM product").fetchone()[0]
            ),
        }
    finally:
        connection.close()


def _queue_safety(database_path: Path) -> dict[str, object]:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        checks: dict[str, list[dict[str, object]]] = {}
        for table, status_column in (
            ("batch", "status"),
            ("batch_variant", "queue_status"),
            ("scheduled_batch_run", "status"),
            ("video_production_job", "status"),
        ):
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if not exists:
                checks[table] = []
                continue
            checks[table] = [
                dict(row)
                for row in connection.execute(
                    f"SELECT {status_column} AS status, COUNT(*) AS count "
                    f"FROM {table} GROUP BY {status_column} ORDER BY {status_column}"
                ).fetchall()
            ]
        active_statuses = {
            "RUNNING",
            "PROCESSING",
            "IN_PROGRESS",
            "GENERATING",
            "UPLOADING",
        }
        active_rows = [
            {"table": table, **row}
            for table, rows in checks.items()
            for row in rows
            if str(row["status"] or "").upper() in active_statuses
            and int(row["count"]) > 0
        ]
        return {
            "safe": not active_rows,
            "active_rows": active_rows,
            "status_counts": checks,
        }
    finally:
        connection.close()


def _registry_summary(database_path: Path) -> dict[str, object]:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        rows = [
            dict(row)
            for row in connection.execute(
                "SELECT cluster, product_type_group, display_name, "
                "matched_scene_strategy_id, scene_coverage_status, "
                "registry_status, auto_classification_enabled, authority_source, "
                "reviewer_id, reviewer_note, reviewed_at "
                "FROM product_strategy_type_registry "
                "ORDER BY cluster, product_type_group"
            ).fetchall()
        ]
        status_counts = {
            str(row["registry_status"]): int(row["count"])
            for row in connection.execute(
                "SELECT registry_status, COUNT(*) AS count "
                "FROM product_strategy_type_registry GROUP BY registry_status"
            ).fetchall()
        }
        return {
            "row_count": len(rows),
            "status_counts": status_counts,
            "rows": rows,
        }
    finally:
        connection.close()


async def _authority_report() -> dict[str, object]:
    from agent.db.schema import close_db
    from agent.services.catalog_coverage_service import (
        build_catalog_authority_matrix,
    )

    try:
        report = await build_catalog_authority_matrix()
        return report.model_dump(mode="json")
    finally:
        await close_db()


def _write_matrix_csv(path: Path, products: list[dict[str, object]]) -> None:
    fields = (
        "product_id",
        "product_name",
        "lifecycle_status",
        "source_category",
        "source_subcategory",
        "source_product_type",
        "product_truth_mapped",
        "mapping_provenance",
        "mapping_reviewer_id",
        "mapping_reviewer_note",
        "cluster",
        "product_type_group",
        "scene_strategy_id",
        "registry_status",
        "review_status",
        "consumer_status",
        "scene_coverage_status",
        "taxonomy_stale",
        "fallback_used",
        "specific_strategy",
        "p4_support_status",
        "terminal_state",
        "terminal_reasons",
        "p6_launch_cohort",
        "blockers",
        "taxonomy_reviewer_id",
        "taxonomy_reviewed_at",
    )
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for product in products:
            row = {field: product.get(field) for field in fields}
            row["terminal_reasons"] = "|".join(
                str(value) for value in product["terminal_reasons"]
            )
            row["blockers"] = "|".join(
                str(value) for value in product["blockers"]
            )
            writer.writerow(row)


def _write_residual_review_queue(
    path: Path,
    products: list[dict[str, object]],
) -> None:
    residual = [
        product
        for product in products
        if product["terminal_state"]
        in {
            "REVIEW_BLOCKED_WITH_EXACT_REASON",
            "INSUFFICIENT_PRODUCT_TRUTH",
        }
    ]
    fields = (
        "product_id",
        "product_name",
        "product_type_group",
        "scene_strategy_id",
        "registry_status",
        "review_status",
        "consumer_status",
        "p4_support_status",
        "terminal_state",
        "terminal_reasons",
        "mapping_provenance",
        "mapping_reviewer_id",
        "taxonomy_reviewer_id",
        "taxonomy_reviewed_at",
    )
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for product in residual:
            row = {field: product.get(field) for field in fields}
            row["terminal_reasons"] = "|".join(
                str(value) for value in product["terminal_reasons"]
            )
            writer.writerow(row)


def _load_deepseek_review_ledger(path: Path) -> dict[str, object]:
    from agent.services.catalog_authority_review_service import (
        CatalogAuthorityMissionReviewLedger,
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    ledger = CatalogAuthorityMissionReviewLedger.model_validate(payload)
    return ledger.model_dump(mode="json")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--expected-product-count", type=int, default=659)
    parser.add_argument("--apply-isolated", action="store_true")
    parser.add_argument("--apply-canonical", action="store_true")
    parser.add_argument("--canonical-database", type=Path)
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--confirm-canonical")
    parser.add_argument("--deepseek-review-ledger", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.apply_isolated and args.apply_canonical:
        raise RuntimeError("P58_APPLY_MODE_MUST_BE_EXCLUSIVE")
    database_path = args.database.resolve()
    canonical_path = (
        args.canonical_database.resolve()
        if args.canonical_database is not None
        else None
    )
    is_canonical = canonical_path is not None and database_path == canonical_path
    if args.apply_canonical:
        if not is_canonical:
            raise RuntimeError("P58_CANONICAL_PATH_MISMATCH")
        if args.confirm_canonical != CANONICAL_CONFIRMATION:
            raise RuntimeError("P58_CANONICAL_CONFIRMATION_REQUIRED")
    if args.apply_isolated and is_canonical:
        raise RuntimeError("P58_ISOLATED_APPLY_TARGETS_CANONICAL_DATABASE")
    if args.apply_canonical and args.deepseek_review_ledger is None:
        raise RuntimeError("P58_CANONICAL_APPLY_REQUIRES_DEEPSEEK_LEDGER")

    apply_requested = args.apply_isolated or args.apply_canonical
    if apply_requested and args.backup_dir is None:
        raise RuntimeError("P58_APPLY_REQUIRES_BACKUP_DIR")
    args.evidence_dir.mkdir(parents=True, exist_ok=True)

    # Bind the repository's official read models to this isolated/canonical DB
    # before importing any agent modules.
    os.environ["FLOW_AGENT_DIR"] = str(database_path.parent)
    if database_path.name != "flow_agent.db":
        raise RuntimeError("P58_DATABASE_MUST_BE_NAMED_FLOW_AGENT_DB")
    deepseek_ledger = (
        _load_deepseek_review_ledger(
            args.deepseek_review_ledger.resolve()
        )
        if args.deepseek_review_ledger is not None
        else {
            "mission_id": MISSION_ID,
            "ledger_status": "NOT_SUPPLIED_FOR_NON_CANONICAL_RUN",
        }
    )

    from agent.services.catalog_authority_apply_service import (
        P58_APPLY_CONFIRMATION,
        apply_catalog_authority,
    )

    queue_proof = _queue_safety(database_path)
    _write_json(args.evidence_dir / "p58-queue-safety.json", queue_proof)
    if args.apply_canonical and not queue_proof["safe"]:
        raise RuntimeError("P58_CANONICAL_QUEUE_NOT_QUIESCENT")

    backup_manifest: dict[str, object] | None = None
    backup_path: Path | None = None
    if apply_requested:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup_path = (
            args.backup_dir.resolve()
            / f"flow_agent.p58-pre-apply-{timestamp}.db"
        )
        backup_manifest = _backup_database(database_path, backup_path)
        if backup_manifest["product_count"] != args.expected_product_count:
            raise RuntimeError("P58_BACKUP_PRODUCT_COUNT_MISMATCH")
        if (
            backup_manifest["integrity_check"] != "ok"
            or backup_manifest["quick_check"] != "ok"
        ):
            raise RuntimeError("P58_BACKUP_INTEGRITY_FAILED")
        _write_json(
            args.evidence_dir / "p58-pre-apply-backup-manifest.json",
            backup_manifest,
        )

    preview = apply_catalog_authority(
        database_path,
        expected_product_count=args.expected_product_count,
        canonical_database_path=canonical_path,
    )
    _write_json(
        args.evidence_dir / "p58-dry-run-plan.json",
        preview.model_dump(mode="json"),
    )

    first = preview
    second = None
    rolled_back = False
    try:
        if apply_requested:
            first = apply_catalog_authority(
                database_path,
                expected_product_count=args.expected_product_count,
                apply=True,
                confirmation=P58_APPLY_CONFIRMATION,
                canonical_database_path=canonical_path,
                allow_canonical=args.apply_canonical,
            )
            second = apply_catalog_authority(
                database_path,
                expected_product_count=args.expected_product_count,
                apply=True,
                confirmation=P58_APPLY_CONFIRMATION,
                canonical_database_path=canonical_path,
                allow_canonical=args.apply_canonical,
            )
            if second.mutation_performed:
                raise RuntimeError("P58_SECOND_APPLY_NOT_IDEMPOTENT")
            _write_json(
                args.evidence_dir / "p58-apply-first-pass.json",
                first.model_dump(mode="json"),
            )
            _write_json(
                args.evidence_dir / "p58-apply-second-pass.json",
                second.model_dump(mode="json"),
            )

        report = asyncio.run(_authority_report())
        if int(report["total_products"]) != args.expected_product_count:
            raise RuntimeError("P58_REPORT_PRODUCT_COUNT_MISMATCH")
        terminal_total = sum(
            int(value) for value in report["terminal_state_counts"].values()
        )
        if terminal_total != args.expected_product_count:
            raise RuntimeError("P58_TERMINAL_STATE_COUNT_MISMATCH")
        if int(report["unknown_product_type_p4_supported_count"]) != 0:
            raise RuntimeError("P58_UNKNOWN_PRODUCT_TYPE_HAS_P4")
        post_apply_checks = _database_checks(database_path)
        if (
            post_apply_checks["integrity_check"] != "ok"
            or post_apply_checks["quick_check"] != "ok"
            or post_apply_checks["product_count"]
            != args.expected_product_count
        ):
            raise RuntimeError("P58_POST_APPLY_DATABASE_CHECK_FAILED")
        _write_json(
            args.evidence_dir / "p58-post-apply-database-checks.json",
            post_apply_checks,
        )

        matrix_json_paths = (
            args.evidence_dir / "p58-final-catalog-authority-matrix.json",
            args.evidence_dir / "final-catalog-coverage-matrix.json",
        )
        for matrix_json_path in matrix_json_paths:
            _write_json(matrix_json_path, report)
        _write_matrix_csv(
            args.evidence_dir / "p58-final-catalog-authority-matrix.csv",
            report["products"],
        )
        _write_matrix_csv(
            args.evidence_dir / "final-catalog-coverage-matrix.csv",
            report["products"],
        )
        _write_residual_review_queue(
            args.evidence_dir / "final-residual-review-queue.csv",
            report["products"],
        )
        blocker_summary = {
            "mission_id": MISSION_ID,
            "terminal_state_counts": report["terminal_state_counts"],
            "blocked_by_reason": report["blocked_by_reason"],
            "matrix_sha256": report["matrix_sha256"],
        }
        for blocker_path in (
            args.evidence_dir / "p58-terminal-state-summary.json",
            args.evidence_dir / "final-blocker-summary.json",
        ):
            _write_json(blocker_path, blocker_summary)
        p6_product_ids = report["p6_launch_cohort_product_ids"]
        p6_cohort_sha256 = _stable_json_sha256(p6_product_ids)
        p6_cohort = {
            "mission_id": MISSION_ID,
            "definition": "VERIFIED + READY + COVERED + P4_SUPPORTED",
            "p6_not_started": True,
            "product_count": report["p6_launch_cohort_count"],
            "product_ids": p6_product_ids,
            "matrix_sha256": report["matrix_sha256"],
            "cohort_sha256": p6_cohort_sha256,
        }
        for cohort_path in (
            args.evidence_dir / "p58-p6-launch-cohort.json",
            args.evidence_dir / "final-p6-launch-cohort.json",
        ):
            _write_json(cohort_path, p6_cohort)
        registry_summary = _registry_summary(database_path)
        for registry_path in (
            args.evidence_dir / "p58-registry-summary.json",
            args.evidence_dir / "final-product-type-registry.json",
        ):
            _write_json(registry_path, registry_summary)
        _write_json(
            args.evidence_dir / "final-deepseek-review-ledger.json",
            deepseek_ledger,
        )
    except Exception:
        if apply_requested and backup_path is not None:
            shutil.copy2(backup_path, database_path)
            restored_sha = _sha256(database_path)
            rolled_back = restored_sha == str(backup_manifest["sha256"])
            _write_json(
                args.evidence_dir / "p58-rollback-result.json",
                {
                    "rolled_back": rolled_back,
                    "restored_sha256": restored_sha,
                    "expected_sha256": backup_manifest["sha256"],
                },
            )
        raise

    result = {
        "mission_id": MISSION_ID,
        "mode": (
            "APPLY_CANONICAL"
            if args.apply_canonical
            else "APPLY_ISOLATED"
            if args.apply_isolated
            else "DRY_RUN"
        ),
        "database_path": str(database_path),
        "backup_manifest": backup_manifest,
        "dry_run": preview.model_dump(mode="json"),
        "first_apply": (
            first.model_dump(mode="json") if apply_requested else None
        ),
        "second_apply": (
            second.model_dump(mode="json") if second is not None else None
        ),
        "rolled_back": rolled_back,
        "terminal_state_counts": report["terminal_state_counts"],
        "p6_launch_cohort_count": report["p6_launch_cohort_count"],
        "p6_not_started": True,
        "p6_cohort_sha256": p6_cohort_sha256,
        "matrix_sha256": report["matrix_sha256"],
        "deepseek_request_count": deepseek_ledger.get("request_count"),
        "post_apply_database_checks": post_apply_checks,
    }
    _write_json(args.evidence_dir / "p58-closure-manifest.json", result)
    _write_json(args.evidence_dir / "final-db-apply-manifest.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"P58_CLOSURE_FAILED:{type(exc).__name__}:{exc}", file=sys.stderr)
        raise
