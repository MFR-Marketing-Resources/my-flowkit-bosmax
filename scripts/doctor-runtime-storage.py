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
