"""Relocate checkout-root absolute Product Truth paths in a staged DB.

The production DB historically contains both relative paths and, for a small
number of repair records, absolute paths under the source checkout.  An
external runtime state root must not retain those checkout-root references.
This helper rewrites only absolute paths proven to be under ``source_root`` to
relative paths.  Absolute paths outside that root fail closed so migration
cannot silently detach a truth-lock byte from its provenance.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


PATH_COLUMNS = ("canonical_source_path", "canonical_cutout_path")


class RelocationError(RuntimeError):
    """Raised when a DB path cannot be safely relocated."""


def _map_path(raw: object, source_root: Path, state_root: Path) -> tuple[str, bool]:
    value = str(raw or "").strip()
    if not value:
        return value, False

    candidate_value = value
    path = Path(value)
    relocated = False
    if path.is_absolute():
        absolute = path.resolve(strict=False)
        try:
            relative = absolute.relative_to(source_root)
        except ValueError as exc:
            raise RelocationError(
                "ABSOLUTE_PATH_OUTSIDE_SOURCE_ROOT:" + value
            ) from exc
        candidate_value = str(relative)
        relocated = True

    candidate = (state_root / candidate_value).resolve(strict=False)
    try:
        candidate.relative_to(state_root)
    except ValueError as exc:
        raise RelocationError("PATH_OUTSIDE_STATE_ROOT:" + candidate_value) from exc
    return candidate_value, relocated


def relocate(db_path: Path, source_root: Path, state_root: Path) -> dict[str, object]:
    db_path = db_path.resolve()
    source_root = source_root.resolve()
    state_root = state_root.resolve()
    if not db_path.is_file():
        raise RelocationError(f"DB_MISSING:{db_path}")

    changes: list[tuple[str, str, str, str]] = []
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(product_visual_truth_lock)"
            ).fetchall()
        }
        missing_columns = sorted(set(PATH_COLUMNS) - columns)
        if missing_columns:
            raise RelocationError(
                "TRUTH_LOCK_COLUMNS_MISSING:" + ",".join(missing_columns)
            )

        rows = connection.execute(
            "SELECT product_id, canonical_source_path, canonical_cutout_path "
            "FROM product_visual_truth_lock"
        ).fetchall()
        for row in rows:
            product_id = str(row["product_id"])
            for column in PATH_COLUMNS:
                old_value = str(row[column] or "").strip()
                new_value, relocated = _map_path(old_value, source_root, state_root)
                if relocated and new_value != old_value:
                    changes.append((product_id, column, old_value, new_value))

        if changes:
            connection.execute("BEGIN IMMEDIATE")
            for product_id, column, _old_value, new_value in changes:
                connection.execute(
                    f"UPDATE product_visual_truth_lock SET {column} = ? "
                    "WHERE product_id = ?",
                    (new_value, product_id),
                )
            connection.commit()

    return {
        "db_path": str(db_path),
        "source_root": str(source_root),
        "state_root": str(state_root),
        "rows_changed": len({change[0] for change in changes}),
        "relocated_absolute_paths": len(changes),
        "relocated_columns": [
            {"product_id": product_id, "column": column}
            for product_id, column, _old_value, _new_value in changes
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    try:
        result = relocate(args.db, args.source_root, args.state_root)
    except (OSError, RelocationError, sqlite3.Error) as exc:
        print(f"RUNTIME_STATE_PATH_RELOCATION_FAILED:{exc}", file=sys.stderr)
        return 1
    if args.as_json:
        print(json.dumps(result, sort_keys=True))
    else:
        for key, value in result.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
