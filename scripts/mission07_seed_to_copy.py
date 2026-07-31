#!/usr/bin/env python
"""BOSMAX-ALL-659-PRODUCT-COMPLETENESS-07C phase 7 — HUB seed -> DRAFT copy promotion.

CREDIT-FREE. `copy_set_service` contains no provider reference at all; the copy content
here is the human-authored HUB workbook material already imported into
`copy_intelligence_seed`, not generated text. This phase deliberately runs BEFORE the
DeepSeek phase so paid generation is only spent on products with no existing source.

It does NOT write `copy_set` rows directly. It drives the existing `generate_copy_set`
service with per-field overrides, so the stored copy contract stays in one place:
field normalisation, `compute_dedupe_key`, the completeness + claim-safety scan and the
resulting status all remain the service's decision. Nothing is approved here — the service
assigns COPY_REVIEW_REQUIRED / DRAFT_COPY and `approved_at` stays NULL.

FIELD MAPPING (only fields the seeds actually carry; `body_script` and `copy_angle` are
empty in every imported seed, so nothing is invented to fill them):
    angle    <- pain_point                 hook <- hook_script
    subhook  <- dream_outcome              cta  <- cta_script
    usp_set  <- key_ingredients_features   (split on newline / bullet / semicolon)

SAFETY
  * `--apply` required; default is a read-only plan.
  * IDEMPOTENT + RESUMABLE: a product that already has a live `copy_set` is skipped, and
    the service's own dedupe key prevents a duplicate row if a seed is promoted twice.
  * Source provenance is preserved: seed_id, workbook, sheet, row, reference_id and
    match_method are written onto the created row.
  * Per-product failures are recorded and skipped; they never abort the cohort.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from agent.db import crud  # noqa: E402
from agent.db.schema import get_db  # noqa: E402
from agent.services.copy_set_service import generate_copy_set  # noqa: E402

OUT_DIR = REPO / "outputs" / "mission-07c-seed-to-copy"
_SPLIT = re.compile(r"[\n;•·]+|\s{2,}")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _usps(raw: str | None) -> list[str]:
    parts = [p.strip(" -–—\t") for p in _SPLIT.split(str(raw or "")) if p and p.strip(" -–—\t")]
    return parts[:3]


async def load_cohort() -> list[dict]:
    """Seeds bound to an ACTIVE product that still has no live copy_set."""
    db = await get_db()
    cur = await db.execute(
        "SELECT s.* FROM copy_intelligence_seed s JOIN product p ON p.id = s.target_product_id "
        "WHERE s.target_product_id IS NOT NULL AND p.lifecycle_status = 'ACTIVE' "
        "AND NOT EXISTS (SELECT 1 FROM copy_set c WHERE c.product_id = p.id "
        "                AND COALESCE(c.archived, 0) = 0) "
        "ORDER BY s.target_product_id")
    rows = [dict(r) for r in await cur.fetchall()]
    await cur.close()
    return rows


async def promote(seed: dict) -> dict:
    pid = seed["target_product_id"]
    payload = {
        "product_id": pid,
        "angle": (seed.get("pain_point") or "").strip() or None,
        "hook": (seed.get("hook_script") or "").strip() or None,
        "subhook": (seed.get("dream_outcome") or "").strip() or None,
        "usp_set": _usps(seed.get("key_ingredients_features")) or None,
        "cta": (seed.get("cta_script") or "").strip() or None,
        "platform": "TIKTOK",
        "language": "BM_MS",
    }
    result = await generate_copy_set(payload)
    row = result.get("copy_set") or result
    csid = row.get("copy_set_id")
    if not csid:
        return {"product_id": pid, "ok": False, "error": "NO_COPY_SET_RETURNED"}

    # preserve where this copy actually came from
    provenance = {}
    try:
        provenance = json.loads(row.get("provenance_json") or "{}")
    except Exception:  # noqa: BLE001 - provenance must never break the promotion
        provenance = {}
    provenance.update({
        "promoted_from": "copy_intelligence_seed",
        "seed_id": seed.get("seed_id"),
        "source_workbook": seed.get("source_workbook"),
        "source_sheet": seed.get("source_sheet"),
        "source_row": seed.get("source_row"),
        "reference_id": seed.get("reference_id"),
        "match_method": seed.get("match_method"),
        "seed_confidence": seed.get("confidence"),
    })
    await crud.update_copy_set(csid, provenance_json=json.dumps(provenance, ensure_ascii=False),
                               source="HUB_SEED_PROMOTION")
    return {"product_id": pid, "ok": True, "copy_set_id": csid,
            "status": row.get("status"), "reused": bool(result.get("deduplicated"))}


async def main_async(args) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cohort = await load_cohort()
    if args.limit:
        cohort = cohort[: args.limit]
    print(f"seed cohort (ACTIVE, no live copy): {len(cohort)}")
    if not args.apply:
        print("PLAN ONLY — nothing written. Re-run with --apply.")
        return 0

    ok, failed = [], []
    for i, seed in enumerate(cohort, 1):
        try:
            res = await promote(seed)
        except Exception as e:  # noqa: BLE001 - one bad seed must not abort the cohort
            res = {"product_id": seed["target_product_id"], "ok": False,
                   "error": type(e).__name__, "detail": str(e)[:200]}
        (ok if res.get("ok") else failed).append(res)
        if i % 25 == 0 or i == len(cohort):
            print(f"  {i}/{len(cohort)} | ok={len(ok)} failed={len(failed)}", flush=True)

    stamp = _stamp()
    (OUT_DIR / f"seed-to-copy-{stamp}.json").write_text(json.dumps(
        {"cohort_size": len(cohort), "promoted": len(ok), "failed": len(failed),
         "promoted_rows": ok, "failures": failed}, indent=2, default=str), encoding="utf-8")
    print(f"\npromoted={len(ok)} failed={len(failed)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--apply", action="store_true")
    p.add_argument("--limit", type=int, default=0)
    return p


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async(build_parser().parse_args())))
