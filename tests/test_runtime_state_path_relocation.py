"""Coverage for external runtime-state Product Truth path relocation."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "relocate-runtime-state-db.py"
)


def _create_db(path: Path, rows: list[tuple[str, str, str]]) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE product_visual_truth_lock ("
            "product_id TEXT PRIMARY KEY, "
            "canonical_source_path TEXT, "
            "canonical_cutout_path TEXT)"
        )
        connection.executemany(
            "INSERT INTO product_visual_truth_lock "
            "(product_id, canonical_source_path, canonical_cutout_path) "
            "VALUES (?, ?, ?)",
            rows,
        )
        connection.commit()


def _run(db: Path, source_root: Path, state_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--db",
            str(db),
            "--source-root",
            str(source_root),
            "--state-root",
            str(state_root),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_relocates_absolute_checkout_paths_and_preserves_missing_evidence(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    state_root = tmp_path / "state"
    source_root.mkdir()
    state_root.mkdir()
    existing = source_root / "data" / "existing.png"
    existing.parent.mkdir()
    existing.write_bytes(b"real-product-byte")
    missing = source_root / "data" / "missing.png"
    db = source_root / "flow_agent.db"
    _create_db(
        db,
        [
            ("existing", str(existing), ""),
            ("missing", str(missing), ""),
            ("relative", "data/relative.png", ""),
        ],
    )

    result = _run(db, source_root, state_root)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["rows_changed"] == 2
    assert payload["relocated_absolute_paths"] == 2
    with sqlite3.connect(db) as connection:
        rows = dict(
            connection.execute(
                "SELECT product_id, canonical_source_path "
                "FROM product_visual_truth_lock"
            ).fetchall()
        )
    assert rows["existing"] == str(Path("data") / "existing.png")
    assert rows["missing"] == str(Path("data") / "missing.png")
    assert rows["relative"] == "data/relative.png"
    assert not Path(rows["existing"]).is_absolute()
    assert not Path(rows["missing"]).is_absolute()


def test_fails_closed_for_absolute_path_outside_source_root(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    state_root = tmp_path / "state"
    source_root.mkdir()
    state_root.mkdir()
    outside = tmp_path / "outside" / "foreign.png"
    db = source_root / "flow_agent.db"
    _create_db(db, [("foreign", str(outside), "")])

    result = _run(db, source_root, state_root)

    assert result.returncode == 1
    assert "ABSOLUTE_PATH_OUTSIDE_SOURCE_ROOT" in result.stderr
    with sqlite3.connect(db) as connection:
        assert connection.execute(
            "SELECT canonical_source_path FROM product_visual_truth_lock "
            "WHERE product_id = 'foreign'"
        ).fetchone()[0] == str(outside)
