#!/usr/bin/env python
"""BOSMAX-ALL-659-PRODUCT-COMPLETENESS-07C phase C — archived source-image recovery.

The archived cohort's images were never DOWNLOADED, but the products still carry their
original marketplace `image_url`. This recovers the REAL source image; it never generates,
substitutes or invents one. DeepSeek is text-only and is not involved.

It drives the EXISTING governed endpoint `POST /api/products/{id}/cache-image`, which is
already the one place that downloads a product image, writes `local_image_path` and sets
`asset_status`. No second downloader and no direct status write.

The archived lifecycle is NOT touched: these products stay ARCHIVED and remain
ARCHIVED_NOT_IN_SCOPE for P4/P6 and production queues. Only the missing catalogue asset is
filled in.

SAFETY
  * `--apply` required; default is a read-only plan.
  * IDEMPOTENT + RESUMABLE: products already DOWNLOADED are skipped.
  * SERIAL by default — the endpoint runs inside the agent, and concurrent load on that
    process is what starves it (measured 2026-08-01).
  * A product with no usable `image_url` is reported as unrecoverable with its exact
    immutable id; it is never marked complete and never given a placeholder.
  * Per-product failures are recorded and skipped; the cohort is never aborted.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

DB = REPO / "flow_agent.db"
OUT_DIR = REPO / "outputs" / "mission-07c-archived-image-recovery"
BASE_URL = "http://127.0.0.1:8100"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_cohort(lifecycle: str) -> tuple[list[dict], list[dict]]:
    """Return (recoverable, unrecoverable) archived products missing their image."""
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        "SELECT id, raw_product_title, image_url, source_url, tiktok_product_url "
        "FROM product WHERE lifecycle_status = ? AND asset_status = 'UNRESOLVED' ORDER BY id",
        (lifecycle,))]
    con.close()
    recoverable = [r for r in rows if str(r.get("image_url") or "").strip()]
    unrecoverable = [r for r in rows if not str(r.get("image_url") or "").strip()]
    return recoverable, unrecoverable


def cache_image(product_id: str, timeout: int) -> tuple[bool, dict]:
    req = urllib.request.Request(
        f"{BASE_URL}/api/products/{product_id}/cache-image", data=b"", method="POST",
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read().decode("utf-8", "replace"))
        ok = str(payload.get("status", "")).lower() == "success"
        return ok, payload
    except urllib.error.HTTPError as e:
        return False, {"error": f"HTTP_{e.code}", "detail": e.read().decode("utf-8", "replace")[:200]}
    except Exception as e:  # noqa: BLE001 - a driver records, it does not raise
        return False, {"error": type(e).__name__, "detail": str(e)[:200]}


async def main_async(args) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    recoverable, unrecoverable = load_cohort(args.lifecycle)
    cohort_total = len(recoverable) + len(unrecoverable)
    recoverable_total = len(recoverable)
    if args.limit:
        recoverable = recoverable[: args.limit]

    print(f"lifecycle              : {args.lifecycle}")
    print(f"missing image          : {cohort_total}")
    print(f"  with source image_url: {recoverable_total}"
          + (f" (this run limited to {len(recoverable)})" if args.limit else ""))
    print(f"  NO source url        : {len(unrecoverable)} (unrecoverable - reported, never faked)")
    if not args.apply:
        print("\nPLAN ONLY — nothing downloaded. Re-run with --apply.")
        return 0

    ok, failed = [], []
    for i, p in enumerate(recoverable, 1):
        t0 = time.monotonic()
        success, payload = await asyncio.to_thread(cache_image, p["id"], args.timeout)
        rec = {"product_id": p["id"], "ok": success, "seconds": round(time.monotonic() - t0, 1),
               "local_image_path": payload.get("local_image_path"),
               "image_asset_status": payload.get("image_asset_status"),
               "error": payload.get("error") or payload.get("detail")}
        (ok if success else failed).append(rec)
        if i % 25 == 0 or i == len(recoverable):
            print(f"  {i}/{len(recoverable)} | ok={len(ok)} failed={len(failed)}", flush=True)

    stamp = _stamp()
    (OUT_DIR / f"image-recovery-{stamp}.json").write_text(json.dumps({
        "lifecycle": args.lifecycle, "attempted": len(recoverable),
        "recovered": len(ok), "failed": len(failed),
        "unrecoverable_no_source_url": [
            {"product_id": r["id"], "title": str(r.get("raw_product_title"))[:80],
             "source_url": r.get("source_url"), "tiktok_product_url": r.get("tiktok_product_url")}
            for r in unrecoverable],
        "recovered_rows": ok, "failures": failed},
        indent=2, default=str), encoding="utf-8")
    print(f"\nrecovered={len(ok)} failed={len(failed)} unrecoverable={len(unrecoverable)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--apply", action="store_true")
    p.add_argument("--lifecycle", default="ARCHIVED")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--timeout", type=int, default=120)
    return p


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async(build_parser().parse_args())))
