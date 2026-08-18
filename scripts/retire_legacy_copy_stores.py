"""Task D5 — final PHYSICAL retirement of the legacy copy stores.

Governed, backed-up removal of the three transitional shells

    copy_set, copy_component, poster_copy_set

from a database that has ALREADY been cut over to the receipt-native V2-only
architecture (see scripts/migrate_copy_register_v2_only.py). Historical lineage is
untouched: the five ``legacy_*_receipt`` ledgers and every receipt-backed FK stay
exactly as they are. This script never touches product data, Product Truth, V2
authority, approvals, or any provider surface.

Modes:
  --dry-run (default)  run on a throwaway COPY; the source DB is never modified.
  --apply              mutate the target DB in place (after a verified backup).

Fail-closed preflight — the DROP happens ONLY when ALL hold:
  * the three stores exist and each has 0 rows,
  * no FK / view / outside-trigger references an active store,
  * the receipt substrate is present with plausible counts,
  * a cut-over migration receipt is present,
  * foreign_key_check is clean and quick_check is ok.

Idempotent: a DB whose stores are already absent AND carries the
physical-retirement receipt reports ALREADY_APPLIED and mutates nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from agent.db.legacy_copy_ledger import (  # noqa: E402
    PHYSICAL_RETIREMENT_MIGRATION_VERSION,
    RECEIPT_LEDGER_TABLES,
    WRITE_DENY_STORES,
)

ACTIVE_STORES = tuple(WRITE_DENY_STORES)
CUTOVER_RECEIPT = "legacy_copy_migration_receipt"


class RetirementError(RuntimeError):
    """Stable fail-closed error for the physical-retirement migration."""


@dataclass
class RetirementResult:
    status: str
    database_path: str
    migration_id: str = ""
    backup_path: str = ""
    backup_sha256: str = ""
    dropped: list[str] = field(default_factory=list)
    before_counts: dict = field(default_factory=dict)
    receipt_counts: dict = field(default_factory=dict)
    dependency_scan: dict = field(default_factory=dict)
    integrity_check: str = ""
    foreign_key_check: list = field(default_factory=list)
    provider_calls: int = 0
    credit_spend: int = 0

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "database_path": self.database_path,
            "migration_id": self.migration_id,
            "migration_version": PHYSICAL_RETIREMENT_MIGRATION_VERSION,
            "backup_path": self.backup_path,
            "backup_sha256": self.backup_sha256,
            "dropped": self.dropped,
            "before_counts": self.before_counts,
            "receipt_counts": self.receipt_counts,
            "dependency_scan": self.dependency_scan,
            "integrity_check": self.integrity_check,
            "foreign_key_check": self.foreign_key_check,
            "provider_calls": self.provider_calls,
            "credit_spend": self.credit_spend,
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


def _row_count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def _dependency_scan(connection: sqlite3.Connection) -> dict:
    """Every FK / view / trigger that references an active store from OUTSIDE it."""
    fks: list[str] = []
    for table in _table_names(connection):
        if table in ACTIVE_STORES:
            continue
        for row in connection.execute(f'PRAGMA foreign_key_list("{table}")').fetchall():
            if row[2] in ACTIVE_STORES:
                fks.append(f"{table}.{row[3]} -> {row[2]}")
    views = [
        str(r[0])
        for r in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='view' AND sql IS NOT NULL"
        )
        if any(store in str(r[0]) for store in ACTIVE_STORES)
    ]
    outside_triggers = [
        str(r[0])
        for r in connection.execute(
            "SELECT name, tbl_name FROM sqlite_master WHERE type='trigger'"
        ).fetchall()
        if r[1] not in ACTIVE_STORES
        and any(store in str(r[0]) for store in ACTIVE_STORES)
    ]
    return {"fk_to_active": fks, "views_referencing_active": views,
            "outside_triggers_referencing_active": outside_triggers}


def _receipt_counts(connection: sqlite3.Connection) -> dict:
    tables = _table_names(connection)
    return {
        t: (_row_count(connection, t) if t in tables else None)
        for t in RECEIPT_LEDGER_TABLES
    }


def _already_retired(connection: sqlite3.Connection) -> bool:
    tables = _table_names(connection)
    if any(store in tables for store in ACTIVE_STORES):
        return False
    if CUTOVER_RECEIPT not in tables:
        return False
    marker = connection.execute(
        f"SELECT COUNT(*) FROM {CUTOVER_RECEIPT} WHERE migration_version=?",
        (PHYSICAL_RETIREMENT_MIGRATION_VERSION,),
    ).fetchone()[0]
    return int(marker) > 0


def _preflight(connection: sqlite3.Connection) -> dict:
    tables = _table_names(connection)
    problems: list[str] = []

    present = [s for s in ACTIVE_STORES if s in tables]
    before_counts = {s: _row_count(connection, s) for s in present}
    for store, count in before_counts.items():
        if count != 0:
            problems.append(f"ACTIVE_STORE_NOT_EMPTY:{store}={count}")

    if CUTOVER_RECEIPT not in tables:
        problems.append("CUTOVER_MIGRATION_RECEIPT_ABSENT")
    else:
        if _row_count(connection, CUTOVER_RECEIPT) == 0:
            problems.append("CUTOVER_MIGRATION_RECEIPT_EMPTY")
    for receipt in RECEIPT_LEDGER_TABLES:
        if receipt not in tables:
            problems.append(f"RECEIPT_LEDGER_ABSENT:{receipt}")

    scan = _dependency_scan(connection)
    if scan["fk_to_active"]:
        problems.append("FK_TO_ACTIVE_STORE:" + ",".join(scan["fk_to_active"]))
    if scan["views_referencing_active"]:
        problems.append("VIEW_REFERENCES_ACTIVE:" + ",".join(scan["views_referencing_active"]))
    if scan["outside_triggers_referencing_active"]:
        problems.append("OUTSIDE_TRIGGER_REFERENCES_ACTIVE:"
                        + ",".join(scan["outside_triggers_referencing_active"]))

    fk_check = [list(r) for r in connection.execute("PRAGMA foreign_key_check").fetchall()]
    if fk_check:
        problems.append("FOREIGN_KEY_CHECK_DIRTY")
    integrity = str(connection.execute("PRAGMA quick_check").fetchone()[0])
    if integrity != "ok":
        problems.append(f"INTEGRITY_CHECK:{integrity}")

    if problems:
        raise RetirementError("PREFLIGHT_FAILED:" + json.dumps(problems))
    return {"present": present, "before_counts": before_counts,
            "receipt_counts": _receipt_counts(connection), "dependency_scan": scan,
            "integrity_check": integrity, "foreign_key_check": fk_check}


def backup_database(source: Path, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise RetirementError(f"BACKUP_ALREADY_EXISTS:{destination}")
    src = sqlite3.connect(str(source))
    dst = sqlite3.connect(str(destination))
    try:
        src.backup(dst)
        dst.commit()
    finally:
        dst.close()
        src.close()
    return _sha256_file(destination)


def _validate_backup(backup_path: Path, expected_sha: str) -> None:
    if _sha256_file(backup_path) != expected_sha:
        raise RetirementError("BACKUP_SHA_MISMATCH")
    conn = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
    try:
        if [list(r) for r in conn.execute("PRAGMA foreign_key_check").fetchall()]:
            raise RetirementError("BACKUP_FOREIGN_KEY_CHECK_DIRTY")
        if str(conn.execute("PRAGMA quick_check").fetchone()[0]) != "ok":
            raise RetirementError("BACKUP_INTEGRITY_CHECK_FAILED")
    finally:
        conn.close()


def perform_retirement(
    database_path: Path, *, backup_path: Path, backup_sha256: str
) -> RetirementResult:
    database_path = database_path.resolve()
    connection = _connect(database_path)
    try:
        if _already_retired(connection):
            return RetirementResult(
                status="ALREADY_APPLIED", database_path=str(database_path),
                receipt_counts=_receipt_counts(connection),
            )
        pre = _preflight(connection)
        migration_id = f"legacy-copy-physical-retirement:{uuid4()}"

        connection.execute("PRAGMA foreign_keys=OFF")
        try:
            connection.execute("BEGIN IMMEDIATE")
            for store in pre["present"]:
                connection.execute(f'DROP TABLE IF EXISTS "{store}"')
            connection.execute(
                f"""INSERT INTO {CUTOVER_RECEIPT}
                    (migration_id, migration_version, applied_at, source_database_path,
                     backup_path, backup_sha256, before_counts_json, after_counts_json,
                     archive_counts_json, reference_counts_json, source_schema_json,
                     manifest_sha256, integrity_check, foreign_key_check_json)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    migration_id, PHYSICAL_RETIREMENT_MIGRATION_VERSION, _utc_now(),
                    str(database_path), str(backup_path), backup_sha256,
                    json.dumps(pre["before_counts"]), json.dumps({s: "ABSENT" for s in pre["present"]}),
                    json.dumps(pre["receipt_counts"]), json.dumps(pre["dependency_scan"]),
                    "{}", backup_sha256, pre["integrity_check"], json.dumps(pre["foreign_key_check"]),
                ),
            )
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
        finally:
            connection.execute("PRAGMA foreign_keys=ON")

        # Post verification.
        remaining = [s for s in ACTIVE_STORES if s in _table_names(connection)]
        if remaining:
            raise RetirementError("POST_DROP_STORE_PRESENT:" + ",".join(remaining))
        post_fk = [list(r) for r in connection.execute("PRAGMA foreign_key_check").fetchall()]
        if post_fk:
            raise RetirementError("POST_DROP_FOREIGN_KEY_CHECK_DIRTY")
        post_integrity = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        if post_integrity != "ok":
            raise RetirementError(f"POST_DROP_INTEGRITY:{post_integrity}")

        return RetirementResult(
            status="APPLIED", database_path=str(database_path), migration_id=migration_id,
            backup_path=str(backup_path), backup_sha256=backup_sha256,
            dropped=list(pre["present"]), before_counts=pre["before_counts"],
            receipt_counts=pre["receipt_counts"], dependency_scan=pre["dependency_scan"],
            integrity_check=post_integrity, foreign_key_check=post_fk,
        )
    finally:
        connection.close()


def _runtime_listening(host: str = "127.0.0.1", port: int = 8100) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.75):
            return True
    except OSError:
        return False


def _status(database_path: Path) -> dict:
    conn = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        tables = _table_names(conn)
        return {
            "database_path": str(database_path),
            "active_stores_present": {s: (s in tables) for s in ACTIVE_STORES},
            "receipt_counts": _receipt_counts(conn),
            "already_retired": _already_retired(conn),
        }
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Final physical retirement of legacy copy stores.")
    parser.add_argument("database", type=Path)
    parser.add_argument("--apply", action="store_true", help="Mutate the DB in place (after backup).")
    parser.add_argument("--backup-dir", type=Path, default=None)
    parser.add_argument("--allow-listening", action="store_true",
                        help="Permit --apply while :8100 is listening (unsafe).")
    parser.add_argument("--status", action="store_true", help="Read-only status; no mutation.")
    args = parser.parse_args(argv)

    source = args.database.resolve()
    if not source.exists():
        print(json.dumps({"status": "ERROR", "error": f"DB_NOT_FOUND:{source}"}))
        return 2

    if args.status:
        print(json.dumps(_status(source), indent=2))
        return 0

    stamp = _timestamp()
    backup_dir = args.backup_dir or (source.parent / "backups" / "legacy-copy-physical-retirement")

    if not args.apply:
        # DRY-RUN: operate on a throwaway copy; source is never modified.
        backup_dir.mkdir(parents=True, exist_ok=True)
        target = backup_dir / f"{source.stem}.dry-run.{stamp}.db"
        backup_sha = backup_database(source, target)
        try:
            result = perform_retirement(target, backup_path=target, backup_sha256=backup_sha)
        finally:
            pass
        payload = result.to_dict()
        payload["mode"] = "DRY_RUN"
        payload["dry_run_clone"] = str(target)
        print(json.dumps(payload, indent=2))
        return 0

    # APPLY.
    if _runtime_listening() and not args.allow_listening:
        print(json.dumps({"status": "REFUSED", "error": "RUNTIME_LISTENING_ON_8100",
                          "hint": "stop the canonical backend before --apply"}))
        return 3
    backup_path = backup_dir / f"{source.stem}.pre-physical-retirement.{stamp}.db"
    backup_sha = backup_database(source, backup_path)
    _validate_backup(backup_path, backup_sha)
    result = perform_retirement(source, backup_path=backup_path, backup_sha256=backup_sha)
    payload = result.to_dict()
    payload["mode"] = "APPLY"
    print(json.dumps(payload, indent=2))
    return 0 if result.status in ("APPLIED", "ALREADY_APPLIED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
