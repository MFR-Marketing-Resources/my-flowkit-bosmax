#!/usr/bin/env python3
"""Export or atomically apply the bounded P7 canonical database delta."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

CANONICAL_CONFIRMATION = "APPLY_P7_TO_MERGED_CANONICAL_DB"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("export", "apply"))
    parser.add_argument("--runtime-dir", required=True, type=Path)
    parser.add_argument("--delta-json", required=True, type=Path)
    parser.add_argument("--asset-bundle-dir", required=True, type=Path)
    parser.add_argument("--baseline-db", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--mission-id", required=True)
    parser.add_argument("--canonical-confirmation", default="")
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    repo_root = Path(__file__).resolve().parents[1]
    runtime_dir = args.runtime_dir.resolve()
    target_db = runtime_dir / "flow_agent.db"
    canonical_repo_db = repo_root / "flow_agent.db"
    if not target_db.is_file():
        raise SystemExit(f"RUNTIME_DB_NOT_FOUND:{target_db}")
    if (
        args.action == "apply"
        and target_db.resolve() == canonical_repo_db.resolve()
        and args.canonical_confirmation != CANONICAL_CONFIRMATION
    ):
        raise SystemExit(
            "CANONICAL_DB_REFUSED: exact confirmation required: "
            f"{CANONICAL_CONFIRMATION}"
        )
    os.environ["FLOW_AGENT_DIR"] = str(runtime_dir)
    sys.path.insert(0, str(repo_root))
    from agent.db.schema import close_db, init_db
    from agent.services import creative_supply_delta_service as delta

    async def initialize_schema() -> None:
        await init_db()
        await close_db()

    asyncio.run(initialize_schema())
    if args.action == "export":
        if not args.baseline_db or not args.run_id:
            raise SystemExit("EXPORT_REQUIRES_BASELINE_DB_AND_RUN_ID")
        result = delta.export_delta(
            baseline_db=args.baseline_db,
            isolated_db=target_db,
            output_path=args.delta_json,
            asset_bundle_dir=args.asset_bundle_dir,
            run_id=args.run_id,
            mission_id=args.mission_id,
        )
    else:
        if args.canonical_confirmation != CANONICAL_CONFIRMATION:
            raise SystemExit(
                "CANONICAL_DB_REFUSED: exact confirmation required: "
                f"{CANONICAL_CONFIRMATION}"
            )
        result = delta.apply_delta(
            canonical_db=target_db,
            delta_path=args.delta_json,
            asset_bundle_dir=args.asset_bundle_dir,
            canonical_runtime_dir=runtime_dir,
            expected_mission_id=args.mission_id,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
