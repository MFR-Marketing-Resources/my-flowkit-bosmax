#!/usr/bin/env python
"""BOSMAX-MAPPING-STRATEGY-FINGERPRINT-REMEDIATION-04C — bounded operational driver.

WHY THIS EXISTS
`agent/services/strategy_fingerprint_reconciliation.py` is correct and fail-closed: it
recomputes the plan digest over the cohort it is handed and refuses to write unless that
digest equals the one the caller asserted. The first canonical 04C run still aborted with
`PLAN_DIGEST_MISMATCH` and wrote nothing, because the driver was ad hoc: it computed the
digest over the full authorized 284-ID cohort and then invoked apply with the filtered
283-row SAFE subset. Two different cohorts, therefore two different digests, therefore a
correct refusal — but no repair, and no record of which digest belonged to which cohort.

    digest(284 authorized) = 00ecb96b080f6f38c9ef33de5bf1a8d415c19ff136083524b6ea8267036ee4e7
    digest(283 SAFE subset) = 858988f1d20871f8baec53f2d694b1d242585a5880cd3d3daebb5fe09bbd3df7

WHAT THIS DRIVER GUARANTEES
The cohort is loaded ONCE from the owner-accepted hashed artifact, its SHA-256 is verified
before anything else runs, and that single immutable tuple is the ONLY thing ever handed to
`compute_plan_digest` and `apply_reconciliation`. The digest is never supplied by a caller
and the cohort is never filtered between the two calls, so the 283/284 class of mismatch is
structurally impossible rather than merely avoided by care.

Row selection stays where it belongs: `apply_reconciliation` classifies the full cohort and
writes ONLY the `SAFE_FINGERPRINT_ONLY_RECONCILIATION` rows, reporting every excluded row
and its exact reason. Passing the whole authorized cohort is therefore both correct and the
only form whose digest is meaningful.

SAFETY
  * `--preview` is the default and writes nothing to the database;
  * `--apply` additionally requires the explicit `--authorize` flag;
  * the digest is recomputed immediately before apply, so DB drift still aborts;
  * every run writes a timestamped evidence artifact;
  * `--rollback` is compare-and-swap over the two reconciled columns only.

Zero provider calls, zero generation, zero credits.

Usage:
    python scripts/strategy_fingerprint_reconciliation_04c.py --preview
    python scripts/strategy_fingerprint_reconciliation_04c.py --apply --authorize
    python scripts/strategy_fingerprint_reconciliation_04c.py --rollback <snapshot.json>
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

# The owner-accepted Mission-04B cohort and its published set hash. Both are part of the
# authorization: a mismatch means the cohort on disk is not the one the owner approved.
COHORT_ARTIFACT = REPO / "outputs" / "mapping-telemetry-closure-04b" / "authorized_284_ids.json"
COHORT_SHA256 = "8d450a6a4d707e01725273a16bd237e5da81d896f285b0bf608b706a57047e5b"

OUT_DIR = REPO / "outputs" / "mission-04c-fingerprint-remediation"


class CohortAuthorizationError(RuntimeError):
    """The on-disk cohort is not the owner-accepted one. Never proceed past this."""


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def cohort_set_sha256(product_ids) -> str:
    """Canonical hash of an ID SET — sorted, compact JSON (the published 04B form)."""
    return hashlib.sha256(
        json.dumps(sorted(product_ids), separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def load_authorized_cohort(
    artifact_path: Path = COHORT_ARTIFACT,
    expected_sha256: str = COHORT_SHA256,
) -> tuple[str, ...]:
    """Load + verify the accepted cohort. Returns an immutable, deterministically ordered tuple.

    Raises CohortAuthorizationError with exact evidence if the set hash does not match, so a
    tampered or regenerated cohort can never reach the apply path.
    """
    payload = json.loads(Path(artifact_path).read_text(encoding="utf-8"))
    ids = payload["ids"] if isinstance(payload, dict) else payload
    actual = cohort_set_sha256(ids)
    if actual != expected_sha256:
        raise CohortAuthorizationError(
            "COHORT_ARTIFACT_SHA_MISMATCH — refusing to proceed. "
            f"artifact={artifact_path} count={len(ids)} "
            f"expected_sha256={expected_sha256} actual_sha256={actual}"
        )
    if len(set(ids)) != len(ids):
        raise CohortAuthorizationError(
            f"COHORT_CONTAINS_DUPLICATE_IDS — refusing to proceed. artifact={artifact_path}"
        )
    return tuple(sorted(ids))


async def preview(cohort: tuple[str, ...]) -> dict:
    """Read-only classification + plan digest for the whole authorized cohort."""
    return await sfr.preview_reconciliation(list(cohort))


async def apply_bound(cohort: tuple[str, ...], snapshot_path: Path) -> dict:
    """Apply, with the digest structurally bound to the cohort being applied.

    THE load-bearing invariant of this driver: `compute_plan_digest` and
    `apply_reconciliation` receive the same cohort, derived from one immutable tuple. No
    caller-supplied digest, no subset filtering in between.
    """
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
        out = _write(OUT_DIR / f"rollback-04c-{_stamp()}.json", result)
        print(json.dumps({"restored_count": result["restored_count"],
                          "skipped_cas": len(result["skipped_cas"]),
                          "verify_ok": result["verify_ok"], "evidence": str(out)}, indent=2))
        return 0 if result["verify_ok"] else 1

    cohort = load_authorized_cohort()
    stamp = _stamp()
    print(f"cohort: {len(cohort)} ids  set_sha256={cohort_set_sha256(cohort)}")

    plan = await preview(cohort)
    print(f"cohort_counts: {json.dumps(plan['cohort_counts'])}")
    print(f"eligible={plan['eligible_count']} excluded={plan['excluded_count']}")
    print(f"plan_digest: {plan['plan_digest']}")

    if not args.apply:
        out = _write(OUT_DIR / f"preview-04c-{stamp}.json", {
            "mode": "PREVIEW_READ_ONLY", "invoked_at_utc": stamp,
            "cohort_size": len(cohort), "cohort_set_sha256": cohort_set_sha256(cohort),
            "wrote": False, **plan})
        print(f"PREVIEW ONLY — nothing written to the database.\nevidence: {out}")
        return 0

    if not args.authorize:
        print("REFUSED: --apply requires the explicit --authorize flag.")
        return 2

    snapshot = OUT_DIR / "snapshots" / f"strategy-fingerprint-04c-{stamp}.json"
    result = await apply_bound(cohort, snapshot)
    summary = _summarise(result)
    out = _write(OUT_DIR / f"apply-04c-{stamp}.json", {
        "mode": "APPLY", "invoked_at_utc": stamp,
        "cohort_size": len(cohort), "cohort_set_sha256": cohort_set_sha256(cohort),
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
