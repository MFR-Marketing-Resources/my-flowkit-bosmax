"""Rehearse P5.7 convergence against an explicitly isolated database.

This command refuses the canonical checkout database and performs no provider
calls. It may refresh system-seeded registry rows and auto-derived taxonomy
rows only inside the selected isolated database.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--expected-product-count", type=int)
    parser.add_argument("--apply-isolated", action="store_true")
    return parser.parse_args()


def _canonical_database(repo_root: Path) -> Path:
    completed = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(completed.stdout.strip()).resolve().parent / "flow_agent.db"


def _validate_isolated_database(database: Path, repo_root: Path) -> Path:
    resolved = database.resolve()
    canonical = _canonical_database(repo_root).resolve()
    if resolved == canonical:
        raise SystemExit("CANONICAL_DATABASE_FORBIDDEN")
    if resolved.name != "flow_agent.db":
        raise SystemExit("DATABASE_MUST_BE_NAMED_FLOW_AGENT_DB")
    if not resolved.is_file():
        raise SystemExit(f"ISOLATED_DATABASE_NOT_FOUND:{resolved}")
    connection = sqlite3.connect(f"file:{resolved.as_posix()}?mode=ro", uri=True)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        connection.close()
    if integrity != "ok":
        raise SystemExit(f"ISOLATED_DATABASE_INTEGRITY_FAILED:{integrity}")
    return resolved


def _write_matrix_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fields = (
        "product_id",
        "product_name",
        "lifecycle_status",
        "source_category",
        "source_subcategory",
        "source_product_type",
        "product_truth_mapped",
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
        "p6_launch_cohort",
        "blockers",
    )
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    **row,
                    "blockers": "|".join(
                        str(reason) for reason in row["blockers"]
                    ),
                }
            )


async def _rehearse(
    *,
    database: Path,
    evidence_dir: Path,
    apply_isolated: bool,
    expected_product_count: int | None,
) -> None:
    os.environ["FLOW_AGENT_DIR"] = str(database.parent)

    from agent.db.schema import close_db
    from agent.models.product_strategy_taxonomy import (
        ProductStrategyTaxonomyBackfillRequest,
        ProductStrategyTypeRegistrySeedRequest,
    )
    from agent.services.catalog_coverage_service import (
        build_catalog_coverage_matrix,
    )
    from agent.services.product_strategy_taxonomy_service import (
        BACKFILL_CONFIRMATION,
        REGISTRY_SEED_CONFIRMATION,
        run_product_strategy_taxonomy_backfill,
        seed_product_strategy_type_registry,
    )

    try:
        seed_request = ProductStrategyTypeRegistrySeedRequest(
            dry_run=not apply_isolated,
            confirm_apply=(
                REGISTRY_SEED_CONFIRMATION if apply_isolated else None
            ),
        )
        registry_result = await seed_product_strategy_type_registry(
            seed_request
        )
        backfill_request = ProductStrategyTaxonomyBackfillRequest(
            dry_run=not apply_isolated,
            confirm_apply=BACKFILL_CONFIRMATION if apply_isolated else None,
        )
        backfill_result = await run_product_strategy_taxonomy_backfill(
            backfill_request
        )
        report = await build_catalog_coverage_matrix()
    finally:
        await close_db()

    if (
        expected_product_count is not None
        and report.total_products != expected_product_count
    ):
        raise SystemExit(
            "PRODUCT_COUNT_MISMATCH:"
            f"expected={expected_product_count}:actual={report.total_products}"
        )
    if report.unknown_product_type_p4_supported_count:
        raise SystemExit("UNKNOWN_PRODUCT_TYPE_HAS_P4_SUPPORT")
    if len(report.products) != report.total_products:
        raise SystemExit("COVERAGE_MATRIX_IS_SAMPLE_BOUNDED")

    evidence_dir.mkdir(parents=True, exist_ok=True)
    report_payload = report.model_dump(mode="json")
    evidence = {
        "database": str(database),
        "database_mode": (
            "ISOLATED_APPLY" if apply_isolated else "ISOLATED_DRY_RUN"
        ),
        "canonical_database_mutated": False,
        "provider_calls": 0,
        "p6_started": False,
        "registry_seed": registry_result.model_dump(mode="json"),
        "taxonomy_backfill": backfill_result.model_dump(mode="json"),
        "coverage": report_payload,
    }
    json_path = evidence_dir / "p57-catalog-coverage-evidence.json"
    json_path.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _write_matrix_csv(
        evidence_dir / "p57-catalog-coverage-matrix.csv",
        report_payload["products"],
    )
    (evidence_dir / "p57-p6-launch-cohort.json").write_text(
        json.dumps(
            {
                "definition": (
                    "VERIFIED + READY + COVERED + P4_SUPPORTED"
                ),
                "count": report.p6_launch_cohort_count,
                "product_ids": report.p6_launch_cohort_product_ids,
                "p6_started": False,
                "matrix_sha256": report.matrix_sha256,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "total_products": report.total_products,
                "product_truth_mapped_count": (
                    report.product_truth_mapped_count
                ),
                "unknown_product_type_count": (
                    report.unknown_product_type_count
                ),
                "unknown_product_type_p4_supported_count": (
                    report.unknown_product_type_p4_supported_count
                ),
                "p4_supported_count": report.p4_supported_count,
                "p6_launch_cohort_count": report.p6_launch_cohort_count,
                "matrix_sha256": report.matrix_sha256,
                "evidence_dir": str(evidence_dir),
            },
            sort_keys=True,
        )
    )


def main() -> None:
    args = _arguments()
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))
    database = _validate_isolated_database(args.database, repo_root)
    asyncio.run(
        _rehearse(
            database=database,
            evidence_dir=args.evidence_dir.resolve(),
            apply_isolated=args.apply_isolated,
            expected_product_count=args.expected_product_count,
        )
    )


if __name__ == "__main__":
    main()
