"""Read-only proof that a runtime state root preserves Product Truth bytes.

This intentionally uses only sqlite3 and hashlib so it can run before the full
agent environment is available. It never opens the database for writes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _path_under_root(root: Path, raw: object) -> tuple[Path | None, str | None]:
    value = str(raw or "").strip()
    if not value:
        return None, "PATH_MISSING"
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return resolved, "PATH_OUTSIDE_STATE_ROOT"
    return resolved, None


def inspect_state(root: Path, db_path: Path) -> dict[str, object]:
    root = root.resolve()
    db_path = db_path.resolve()
    result: dict[str, object] = {
        "state_root": str(root),
        "db_path": str(db_path),
        "db_exists": db_path.is_file(),
        "db_size_bytes": db_path.stat().st_size if db_path.is_file() else None,
        "product_count": None,
        "truth_lock_rows": 0,
        "approved_truth_locks": 0,
        "approved_missing_bytes": 0,
        "approved_sha_mismatches": 0,
        "truth_lock_paths_outside_root": 0,
        "truth_lock_paths_missing": 0,
        "truth_lock_paths_sha_mismatch": 0,
        "error": None,
    }
    if not db_path.is_file():
        result["error"] = "DB_MISSING"
        return result

    uri = f"file:{db_path.as_posix()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True) as connection:
            connection.row_factory = sqlite3.Row
            result["product_count"] = int(
                connection.execute("SELECT COUNT(*) FROM product").fetchone()[0]
            )
            rows = connection.execute(
                "SELECT product_id, review_status, canonical_source_path, canonical_sha256, "
                "canonical_cutout_path, canonical_cutout_sha256 "
                "FROM product_visual_truth_lock"
            ).fetchall()
            result["truth_lock_rows"] = len(rows)
            for row in rows:
                approved = str(row["review_status"] or "").upper() == "APPROVED"
                if approved:
                    result["approved_truth_locks"] = int(result["approved_truth_locks"]) + 1
                row_missing = False
                row_mismatch = False
                for path_key, sha_key in (
                    ("canonical_source_path", "canonical_sha256"),
                    ("canonical_cutout_path", "canonical_cutout_sha256"),
                ):
                    path, path_error = _path_under_root(root, row[path_key])
                    if path_error == "PATH_OUTSIDE_STATE_ROOT":
                        result["truth_lock_paths_outside_root"] = int(result["truth_lock_paths_outside_root"]) + 1
                        row_missing = True
                        continue
                    if path is None or not path.is_file() or path.stat().st_size <= 0:
                        result["truth_lock_paths_missing"] = int(result["truth_lock_paths_missing"]) + 1
                        row_missing = True
                        continue
                    if _sha256(path) != str(row[sha_key] or "").strip().lower():
                        result["truth_lock_paths_sha_mismatch"] = int(result["truth_lock_paths_sha_mismatch"]) + 1
                        row_mismatch = True
                if approved and row_missing:
                    result["approved_missing_bytes"] = int(result["approved_missing_bytes"]) + 1
                if approved and row_mismatch:
                    result["approved_sha_mismatches"] = int(result["approved_sha_mismatches"]) + 1
    except sqlite3.Error as exc:
        result["error"] = f"SQLITE_READ_FAILED:{exc}"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--db", type=Path)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    report = inspect_state(root, (args.db or root / "flow_agent.db").resolve())
    if args.as_json:
        print(json.dumps(report, sort_keys=True))
    else:
        for key, value in report.items():
            print(f"{key}: {value}")
    failed = bool(report["error"])
    if args.require_complete:
        failed = failed or any(
            int(report[key]) > 0
            for key in (
                "approved_missing_bytes",
                "approved_sha_mismatches",
                "truth_lock_paths_outside_root",
            )
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
