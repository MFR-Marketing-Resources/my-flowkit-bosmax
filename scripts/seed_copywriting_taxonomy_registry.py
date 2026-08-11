"""Plan/apply the workbook-backed copywriting taxonomy registry seed.

The default is a dry run. Applying requires the explicit confirmation token and
only writes the additive registry table; Product Truth and existing taxonomy
rows are not modified.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent.db.schema import close_db, init_db
from agent.services.copywriting_taxonomy_service import (
    SEED_CONFIRMATION,
    seed_copywriting_taxonomy_registry,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Seed the copywriting taxonomy registry from its committed authority snapshot."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan changes without writing (the default).",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Apply only the additive registry changes.",
    )
    parser.add_argument(
        "--confirm",
        default=None,
        help=f"Required with --apply: {SEED_CONFIRMATION}",
    )
    return parser


async def _run(apply: bool, confirmation: str | None) -> dict:
    await init_db()
    try:
        return await seed_copywriting_taxonomy_registry(
            dry_run=not apply,
            confirm_apply=confirmation,
        )
    finally:
        await close_db()


def main() -> int:
    args = _parser().parse_args()
    try:
        result = asyncio.run(_run(args.apply, args.confirm))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
