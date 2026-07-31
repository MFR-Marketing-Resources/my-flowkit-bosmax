#!/usr/bin/env python
"""BOSMAX-ALL-659-PRODUCT-COMPLETENESS-07C — bounded, resumable DeepSeek copy runner.

Drives the GOVERNED BOSMAX route `POST /api/copy-sets/ai-assist` once per product. It is a
driver, not a second copy pipeline: grounding, claim gating, DRAFT status, provenance and
provider resolution all stay inside the existing service. There is no direct-provider
bypass and no credential handling here — the runner never sees or transports a secret.

SAFETY / COST
  * `--execute` is required; the default is a read-only plan that spends nothing.
  * The cohort is loaded from the accepted Mission-07 artifact and its SHA-256 is verified
    before any call, so the spend set can never silently drift.
  * IDEMPOTENT + RESUMABLE: a product that already has a non-archived `copy_set` row is
    skipped, so re-running after an interruption only bills the remainder.
  * SERIAL BY DEFAULT (`--concurrency 1`). Measured 2026-07-31: the route performs a
    synchronous provider call, so 3 concurrent requests saturated the local agent — every
    one failed `AI_COPY_ASSIST_CALL_FAILED: The read operation timed out` (HTTP 502) and
    `/health` stopped answering until the load was removed. This is the known
    starve-the-event-loop hazard. Raise concurrency only with fresh evidence.
  * Capped retries with exponential backoff, and a hard `--limit`.
  * Progress is appended to a JSONL ledger after every product, so an interrupted run
    still has exact per-ID accounting.
  * DRAFT only. The route persists `COPY_REVIEW_REQUIRED`; nothing here approves anything.

Usage:
    python scripts/mission07_copy_generation_runner.py                 # plan only
    python scripts/mission07_copy_generation_runner.py --execute
    python scripts/mission07_copy_generation_runner.py --execute --limit 10 --concurrency 3
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import urllib.error  # noqa: E402
import urllib.request  # noqa: E402

DB = REPO / "flow_agent.db"
COHORT_FILE = REPO / "outputs" / "mission-07-all-659-completeness" / "cohorts.json"
COHORT_KEY = "COPY_REQUIRES_AI_CREDIT"
COHORT_SHA256 = "045398e08e8a36c2dc62c72de1eeeb89b058f29773bb889ab4e2d7602d9adba1"
OUT_DIR = REPO / "outputs" / "mission-07c-copy-generation"
BASE_URL = "http://127.0.0.1:8100"
ENDPOINT = "/api/copy-sets/ai-assist"


class CohortAuthorizationError(RuntimeError):
    """The on-disk cohort is not the accepted one. Never spend against it."""


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def cohort_sha256(ids) -> str:
    return hashlib.sha256(json.dumps(sorted(ids), separators=(",", ":")).encode()).hexdigest()


def load_cohort() -> list[str]:
    payload = json.loads(COHORT_FILE.read_text(encoding="utf-8"))[COHORT_KEY]
    ids = payload["product_ids"]
    actual = cohort_sha256(ids)
    if actual != COHORT_SHA256:
        raise CohortAuthorizationError(
            f"COHORT_SHA_MISMATCH — refusing to spend. expected={COHORT_SHA256} actual={actual}")
    return sorted(ids)


def already_has_copy() -> set[str]:
    """Products with a live copy_set row — the resumability + idempotency key."""
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True, timeout=30)
    try:
        return {r[0] for r in con.execute(
            "SELECT DISTINCT product_id FROM copy_set WHERE COALESCE(archived,0)=0")}
    finally:
        con.close()


def lane_ready() -> dict:
    with urllib.request.urlopen(f"{BASE_URL}/api/ai-providers", timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))
    lane = next((l for l in data.get("lanes", []) if l.get("lane") == "text_assist"), None)
    if not lane or lane.get("status") != "READY" or not lane.get("execution_enabled"):
        raise RuntimeError(f"TEXT_ASSIST_LANE_NOT_READY: {lane}")
    return {"provider_id": lane["provider_id"], "model_id": lane["model_id"],
            "status": lane["status"], "execution_enabled": lane["execution_enabled"]}


def _post(product_id: str, timeout: int) -> tuple[bool, dict]:
    body = json.dumps({"product_id": product_id, "platform": "TIKTOK",
                       "language": "BM_MS"}).encode("utf-8")
    req = urllib.request.Request(f"{BASE_URL}{ENDPOINT}", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read().decode("utf-8", "replace"))
        cands = payload.get("candidates") or []
        cs = (cands[0] or {}).get("copy_set") if cands else None
        if not cs or not cs.get("copy_set_id"):
            return False, {"error": "NO_CANDIDATE_PERSISTED"}
        return True, {"copy_set_id": cs["copy_set_id"], "status": cs.get("status"),
                      "provider_id": (payload.get("provider") or {}).get("provider_id"),
                      "model_id": (payload.get("provider") or {}).get("model_id"),
                      "grounded": (payload.get("grounding") or {}).get("grounded")}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        return False, {"error": f"HTTP_{e.code}", "detail": detail}
    except Exception as e:  # noqa: BLE001 - a driver must record, not raise
        return False, {"error": type(e).__name__, "detail": str(e)[:300]}


async def run_one(pid: str, sem: asyncio.Semaphore, retries: int, timeout: int) -> dict:
    async with sem:
        for attempt in range(1, retries + 2):
            t0 = time.monotonic()
            ok, info = await asyncio.to_thread(_post, pid, timeout)
            dur = round(time.monotonic() - t0, 1)
            if ok:
                return {"product_id": pid, "ok": True, "attempt": attempt, "seconds": dur, **info}
            if attempt <= retries:
                await asyncio.sleep(min(60, 5 * (2 ** (attempt - 1))))  # 5s, 10s, 20s ...
        return {"product_id": pid, "ok": False, "attempt": attempt, "seconds": dur, **info}


async def main_async(args) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cohort = load_cohort()
    done = already_has_copy()
    pending = [p for p in cohort if p not in done]
    if args.limit:
        pending = pending[: args.limit]

    lane = lane_ready()
    print(f"cohort           : {len(cohort)} (sha256 verified)")
    print(f"already complete : {len(cohort) - len([p for p in cohort if p not in done])}")
    print(f"pending this run : {len(pending)}")
    print(f"lane             : {lane['provider_id']} / {lane['model_id']} ({lane['status']})")
    print(f"concurrency={args.concurrency} retries={args.retries} timeout={args.timeout}s")

    if not args.execute:
        print("\nPLAN ONLY — no provider call made. Re-run with --execute to generate.")
        return 0

    stamp = _stamp()
    ledger = OUT_DIR / f"generation-ledger-{stamp}.jsonl"
    sem = asyncio.Semaphore(args.concurrency)
    tasks = [asyncio.create_task(run_one(p, sem, args.retries, args.timeout)) for p in pending]

    ok_ids, fail = [], []
    with ledger.open("a", encoding="utf-8") as fh:
        for i, coro in enumerate(asyncio.as_completed(tasks), 1):
            res = await coro
            fh.write(json.dumps(res) + "\n")
            fh.flush()
            if res["ok"]:
                ok_ids.append(res["product_id"])
            else:
                fail.append(res)
            if i % 10 == 0 or i == len(tasks):
                print(f"  {i}/{len(tasks)} done | ok={len(ok_ids)} fail={len(fail)}", flush=True)

    summary = {
        "invoked_at_utc": stamp, "cohort_size": len(cohort),
        "cohort_sha256": COHORT_SHA256, "attempted": len(pending),
        "succeeded": len(ok_ids), "failed": len(fail),
        "lane": lane, "succeeded_ids": sorted(ok_ids),
        "failures": fail, "ledger": str(ledger),
    }
    (OUT_DIR / f"generation-summary-{stamp}.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nsucceeded={len(ok_ids)} failed={len(fail)}")
    print(f"ledger : {ledger}")
    return 0 if not fail else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--execute", action="store_true", help="actually call the provider (spends credit)")
    p.add_argument("--limit", type=int, default=0, help="cap products this run (0 = all pending)")
    p.add_argument("--concurrency", type=int, default=1,
                   help="SERIAL by default; >1 saturates the agent and 502s (see module docstring)")
    p.add_argument("--retries", type=int, default=2)
    p.add_argument("--timeout", type=int, default=240)
    return p


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async(build_parser().parse_args())))
