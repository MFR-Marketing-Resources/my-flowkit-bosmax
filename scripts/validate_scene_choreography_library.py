#!/usr/bin/env python3
"""Validate the entire scene_choreography_v2 library and print actionable failures."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo))
    from agent.services.scene_choreography_catalog import (
        SPECS,
        action_coverage_receipt,
        all_choreography_variants,
        coverage_map,
        library_choreography_sha256,
    )
    from agent.services.scene_strategy_library import SCENE_STRATEGIES

    failures: list[str] = []
    try:
        catalog = all_choreography_variants()
        receipt = action_coverage_receipt()
    except Exception as exc:
        print(f"FAIL catalog_build: {exc}")
        return 2
    if len(receipt) != 242:
        failures.append(f"action receipt count {len(receipt)} != 242")
    explicit = [row for row in receipt if row["coverage"] == "EXPLICIT"]
    blocked = [row for row in receipt if row["coverage"] == "BLOCKED"]
    if len(blocked) != 3 or len(explicit) != 239:
        failures.append(f"action coverage split explicit={len(explicit)} blocked={len(blocked)}")
    if any(not row["choreography_id"] or not row["step_numbers"] for row in explicit):
        failures.append("explicit action missing choreography mapping")
    rows = coverage_map()
    live_ids = set(SCENE_STRATEGIES)
    spec_ids = set(SPECS)
    if live_ids != spec_ids:
        failures.append(f"inventory mismatch live={sorted(live_ids - spec_ids)} extra={sorted(spec_ids - live_ids)}")
    if "GENERIC_FALLBACK" in catalog and catalog["GENERIC_FALLBACK"]:
        failures.append("GENERIC_FALLBACK must have zero production variants")
    for row in rows:
        if row["strategy_id"] == "GENERIC_FALLBACK":
            if row["production_eligible"] or row["choreography_variant_count"] != 0:
                failures.append("GENERIC_FALLBACK leaked into production")
            continue
        if not row["production_eligible"] or row["choreography_variant_count"] < 1:
            failures.append(f"{row['strategy_id']} missing production choreography")
    counts = {key: 0 for key in ("P0_REWRITE", "P1_REWRITE", "P2_STATIC", "BLOCK")}
    for row in rows:
        counts[str(row["audit_classification"])] += 1
    print(json.dumps(
        {
            "ok": not failures,
            "live_strategy_count": len(SCENE_STRATEGIES),
            "classification_counts": counts,
            "variant_count": sum(int(row["choreography_variant_count"]) for row in rows),
            "action_receipt_count": len(receipt),
            "explicit_actions": len(explicit),
            "blocked_actions": len(blocked),
            "library_choreography_sha256": library_choreography_sha256(),
            "failures": failures,
            "coverage": rows,
        },
        indent=2,
    ))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
