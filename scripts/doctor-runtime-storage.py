"""Runtime-storage doctor.

Run BEFORE using the dashboard when products/authority look empty:

    python scripts/doctor-runtime-storage.py

Prints the active repo root, BASE_DIR, effective DB path, live product/queue
counts, and git branch/sha for THIS checkout, then flags the wrong-worktree
condition (queue rows present but zero products) that produced the audit's empty
:8100 backend. Read-only: no writes, no migration. Never prints secrets.

Note: this reports the checkout it is RUN FROM. To prove what the *running*
:8100 agent is bound to, also call GET /api/operator/runtime-storage-status
(that runs inside the live process).
"""

import asyncio
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import config  # noqa: E402
from agent.db import crud  # noqa: E402
from agent.db.schema import close_db  # noqa: E402


def _git(*args: str) -> str:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=str(config.BASE_DIR),
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except Exception:
        return "unknown"


def _resolve_under_base(value) -> Path:
    """Resolve a stored server path the way the truth-lock service does."""
    p = Path(str(value or "").strip())
    if not str(value or "").strip():
        return Path(config.BASE_DIR) / "__missing__"
    if not p.is_absolute():
        p = Path(config.BASE_DIR) / p
    return p


def _truth_lock_byte_integrity() -> dict:
    """Existence check of canonical truth-lock bytes vs the DB SSOT (read-only).

    Detects the byte-store desync where DB rows reference canonical source/cutout
    files that are ABSENT from the runtime store — the condition that makes cutouts
    show 'Not available' and (pre-tombstone) blocked REPLACE with a 409. Existence
    based (no hashing) for speed; the DB remains the audit record either way.
    """
    db_path = Path(str(config.DB_PATH))
    result = {"table": True, "rows": 0, "bytes_present": 0, "bytes_missing": 0}
    if not db_path.is_file():
        result["table"] = False
        return result
    try:
        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT canonical_source_path, canonical_cutout_path "
                "FROM product_visual_truth_lock"
            ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            result["table"] = False
            return result
        raise
    result["rows"] = len(rows)
    for r in rows:
        src = _resolve_under_base(r["canonical_source_path"])
        cut = _resolve_under_base(r["canonical_cutout_path"])
        if src.is_file() and cut.is_file():
            result["bytes_present"] += 1
        else:
            result["bytes_missing"] += 1
    return result


async def main() -> int:
    db_path = Path(str(config.DB_PATH))
    print("=== BOSMAX runtime-storage doctor ===")
    print(f"cwd:            {os.getcwd()}")
    print(f"base_dir:       {config.BASE_DIR}")
    print(f"config_db_path: {config.DB_PATH}")
    print(f"db_exists:      {db_path.exists()}")
    print(f"flow_agent_dir_override: {os.environ.get('FLOW_AGENT_DIR') or '(none)'}")
    print(f"git_branch:     {_git('rev-parse', '--abbrev-ref', 'HEAD')}")
    print(f"git_sha:        {_git('rev-parse', '--short', 'HEAD')}")

    warnings: list[str] = []
    try:
        product_count = await crud.count_products()
        manual_count = await crud.count_products(source="MANUAL")
        queue_count = int((await crud.get_bulk_queue_stats()).get("total", 0))
        print(f"product_count:  {product_count}")
        print(f"manual_count:   {manual_count}")
        print(f"queue_count:    {queue_count}")
        if product_count == 0 and queue_count > 0:
            warnings.append(
                "ACTIVE_STORAGE_HAS_QUEUE_BUT_ZERO_PRODUCTS — likely WRONG worktree DB"
            )
        if product_count == 0 and manual_count == 0:
            warnings.append("ACTIVE_STORAGE_HAS_ZERO_MANUAL_PRODUCTS")
    except Exception as exc:
        warnings.append(f"STORAGE_READ_FAILED:{exc}")

    try:
        tl = _truth_lock_byte_integrity()
        if not tl["table"]:
            print("truth_lock:     (no product_visual_truth_lock table)")
        else:
            print(f"truth_lock_rows:          {tl['rows']}")
            print(f"truth_lock_bytes_present: {tl['bytes_present']}")
            print(f"truth_lock_bytes_missing: {tl['bytes_missing']}")
            if tl["bytes_missing"] > 0:
                warnings.append(
                    f"TRUTH_LOCK_BYTES_MISSING — {tl['bytes_missing']}/{tl['rows']} locks "
                    "have no canonical bytes in the runtime store (cutouts show 'Not "
                    "available'; REPLACE now tombstones instead of blocking). Recover with "
                    "scripts/repair-truth-lock-bytes-from-worktree.py or see "
                    "docs/incident-truth-lock-byte-store-desync.md."
                )
    except Exception as exc:
        warnings.append(f"TRUTH_LOCK_INTEGRITY_READ_FAILED:{exc}")

    await close_db()  # release the aiosqlite connection thread so we exit cleanly
    if warnings:
        print("\nWARNINGS:")
        for w in warnings:
            print(f"  ! {w}")
        return 1
    print("\nOK: storage looks bound and populated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
