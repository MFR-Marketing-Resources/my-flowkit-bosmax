#!/usr/bin/env python
"""BOSMAX-PI-EXCEPTION-REGRESSION-08E — bounded fingerprint reconciliation driver.

WHY THIS EXISTS
The 08E incident audit proved three ACTIVE products carried a STALE product fingerprint
whose STRATEGY BINDING was provably unchanged (all six BINDING_FIELDS identical, registry
ACTIVE and matched). Two are `SAFE_FINGERPRINT_ONLY_RECONCILIATION`; the third
(`8e75f1a8...`) is REVIEW_REQUIRED / BLOCKED_REVIEW_REQUIRED and is DELIBERATELY EXCLUDED
by owner instruction — it must stay in review.

This driver reuses `agent/services/strategy_fingerprint_reconciliation.py` unchanged. It
adds only the cohort-authorization wrapper, exactly as
`strategy_fingerprint_reconciliation_04c.py` does for the Mission-04C cohort. That driver's
load-bearing invariant is preserved verbatim:

    ONE immutable cohort tuple is the ONLY thing handed to BOTH `compute_plan_digest`
    and `apply_reconciliation`, with no filtering in between.

That is what makes the 283/284 `PLAN_DIGEST_MISMATCH` class of failure structurally
impossible rather than merely avoided by care. Row selection stays inside
`apply_reconciliation`, which classifies the cohort and writes ONLY the SAFE rows.

SAFETY
  * `--preview` is the default and writes nothing to the database;
  * `--apply` additionally requires the explicit `--authorize` flag;
  * the cohort set hash is verified before anything else runs;
  * an explicit forbidden-ID guard refuses the excluded product even if it is added later;
  * the digest is recomputed immediately before apply, so DB drift still aborts;
  * every run writes a timestamped evidence artifact;
  * `--rollback` is compare-and-swap over the two reconciled columns only.

Only `product_strategy_taxonomy.product_fingerprint` and `.updated_at` can ever be written.
Zero provider calls, zero generation, zero credits.

Usage:
    python scripts/strategy_fingerprint_reconciliation_08e.py --preview
    python scripts/strategy_fingerprint_reconciliation_08e.py --apply --authorize
    python scripts/strategy_fingerprint_reconciliation_08e.py --rollback <snapshot.json>
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))  # allow `python scripts/...` to import the agent package

from agent.services import strategy_fingerprint_reconciliation as sfr  # noqa: E402

# The owner-authorized 08E cohort. `8e75f1a8-ba43-444e-8b40-c71d140c76c5` is EXCLUDED by
# explicit instruction and must never be added here — it stays REVIEW_REQUIRED.
AUTHORIZED_08E_IDS: tuple[str, ...] = (
    "013b7710-a55e-4053-9224-e1149f052f57",
    "ae47b55b-58d4-441e-97d3-0d6c785bb530",
)
# sha256 of json.dumps(sorted(ids), separators=(",", ":")) — the published 04B/04C set form.
COHORT_SHA256 = "1967d82e6ac2d2574d6c4855e6ded6aa450625434da020f36e91fe3afcaeea49"

# Must never be reconciled by this driver.
FORBIDDEN_IDS: frozenset[str] = frozenset({"8e75f1a8-ba43-444e-8b40-c71d140c76c5"})

OUT_DIR = REPO / "outputs" / "mission-08e-fingerprint-recovery"


class CohortAuthorizationError(RuntimeError):
    """The cohort is not the owner-accepted one. Never proceed past this."""


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def cohort_set_sha256(product_ids) -> str:
    """Canonical hash of an ID SET — sorted, compact JSON (the published 04B/04C form)."""
    return hashlib.sha256(
        json.dumps(sorted(product_ids), separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def load_authorized_cohort(
    ids: tuple[str, ...] = AUTHORIZED_08E_IDS,
    expected_sha256: str = COHORT_SHA256,
) -> tuple[str, ...]:
    """Verify + freeze the accepted cohort into an immutable, deterministically ordered tuple."""
    actual = cohort_set_sha256(ids)
    if actual != expected_sha256:
        raise CohortAuthorizationError(
            "COHORT_SHA_MISMATCH — refusing to proceed. "
            f"count={len(ids)} expected_sha256={expected_sha256} actual_sha256={actual}"
        )
    if len(set(ids)) != len(ids):
        raise CohortAuthorizationError("COHORT_CONTAINS_DUPLICATE_IDS — refusing to proceed.")
    forbidden = FORBIDDEN_IDS & set(ids)
    if forbidden:
        raise CohortAuthorizationError(
            f"COHORT_CONTAINS_FORBIDDEN_IDS — refusing to proceed. ids={sorted(forbidden)}"
        )
    return tuple(sorted(ids))


async def preview(cohort: tuple[str, ...]) -> dict:
    """Read-only classification + plan digest for the whole authorized cohort."""
    return await sfr.preview_reconciliation(list(cohort))


async def apply_bound(cohort: tuple[str, ...], snapshot_path: Path) -> dict:
    """Apply, with the digest structurally bound to the cohort being applied."""
    ids = list(cohort)
    digest = await sfr.compute_plan_digest(ids)
    return await sfr.apply_reconciliation(
        ids,
        authorize=True,
        expected_plan_digest=digest,
        snapshot_path=str(snapshot_path),
    )


def _write(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def _summarise(result: dict) -> dict:
    """Evidence-shaped summary — never silently drops an abort reason."""
    return {
        "authorized": result.get("authorized"),
        "wrote": result.get("wrote"),
        "aborted": result.get("aborted"),
        "expected_plan_digest": result.get("expected_plan_digest"),
        "live_digest": result.get("live_digest"),
        "changed_count": result.get("changed_count"),
        "excluded_count": result.get("excluded_count"),
        "rowcount_failures": result.get("rowcount_failures"),
        "verify_failures": result.get("verify_failures"),
        "applied_updated_at": result.get("applied_updated_at"),
        "durable_snapshot": result.get("durable_snapshot"),
    }


async def main_async(args: argparse.Namespace) -> int:
    if args.rollback:
        result = await sfr.rollback_from_snapshot(args.rollback)
        out = _write(OUT_DIR / f"rollback-08e-{_stamp()}.json", result)
        print(json.dumps({"restored_count": result["restored_count"],
                          "skipped_cas": len(result["skipped_cas"]),
                          "verify_ok": result["verify_ok"], "evidence": str(out)}, indent=2))
        return 0 if result["verify_ok"] else 1

    cohort = load_authorized_cohort()
    stamp = _stamp()
    print(f"cohort: {len(cohort)} ids  set_sha256={cohort_set_sha256(cohort)}")
    print(f"excluded by instruction: {sorted(FORBIDDEN_IDS)}")

    plan = await preview(cohort)
    print(f"cohort_counts: {json.dumps(plan['cohort_counts'])}")
    print(f"eligible={plan['eligible_count']} excluded={plan['excluded_count']}")
    print(f"plan_digest: {plan['plan_digest']}")

    if not args.apply:
        out = _write(OUT_DIR / f"preview-08e-{stamp}.json", {
            "mode": "PREVIEW_READ_ONLY", "invoked_at_utc": stamp,
            "cohort_size": len(cohort), "cohort_set_sha256": cohort_set_sha256(cohort),
            "excluded_by_instruction": sorted(FORBIDDEN_IDS),
            "wrote": False, **plan})
        print(f"PREVIEW ONLY — nothing written to the database.\nevidence: {out}")
        return 0

    if not args.authorize:
        print("REFUSED: --apply requires the explicit --authorize flag.")
        return 2

    snapshot = OUT_DIR / "snapshots" / f"strategy-fingerprint-08e-{stamp}.json"
    result = await apply_bound(cohort, snapshot)
    summary = _summarise(result)
    out = _write(OUT_DIR / f"apply-08e-{stamp}.json", {
        "mode": "APPLY", "invoked_at_utc": stamp,
        "cohort_size": len(cohort), "cohort_set_sha256": cohort_set_sha256(cohort),
        "excluded_by_instruction": sorted(FORBIDDEN_IDS),
        "preview_plan_digest": plan["plan_digest"],
        "preview_eligible_count": plan["eligible_count"],
        **summary,
        "changed": result.get("changed"), "excluded": result.get("excluded"),
    })
    print(json.dumps(summary, indent=2))
    print(f"evidence: {out}")
    return 0 if result.get("wrote") else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--preview", action="store_true",
                   help="read-only classification + digest (default)")
    p.add_argument("--apply", action="store_true",
                   help="reconcile the SAFE rows; requires --authorize")
    p.add_argument("--authorize", action="store_true",
                   help="explicit owner authorization for the bounded mutation")
    p.add_argument("--rollback", metavar="SNAPSHOT",
                   help="compare-and-swap rollback from a durable snapshot")
    return p


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async(build_parser().parse_args())))
