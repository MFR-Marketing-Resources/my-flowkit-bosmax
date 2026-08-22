"""One-time repair: restore missing truth-lock canonical bytes from a fallback store.

The runtime byte store (``BASE_DIR/data/exact-product/...``) can be separated from
the promoted ``flow_agent.db`` — e.g. cutouts generated inside a since-pruned
worktree. This script restores EXACT, SHA-verified byte copies from a fallback root
(default: the cutout-bind worktree) into the runtime store.

Safety invariants (why this cannot corrupt the audit chain):
  * It NEVER overwrites a target whose SHA already matches the DB expectation.
  * It ONLY writes bytes whose SHA equals the DB's recorded expected hash, verified
    again after the copy. A mismatched candidate is skipped, never written.
  * Read-only unless ``--apply`` is passed.

    python scripts/repair-truth-lock-bytes-from-worktree.py            # dry-run
    python scripts/repair-truth-lock-bytes-from-worktree.py --apply    # write

See docs/incident-truth-lock-byte-store-desync.md for the durable cure.
"""
import argparse
import hashlib
import shutil
import sqlite3
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import config  # noqa: E402

DEFAULT_FALLBACK = (
    Path(config.BASE_DIR)
    / ".claude" / "worktrees" / "product-cutout-bind-automation-20260808"
)


def _sha256(p: Path) -> str:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return ""


def _resolve(root: Path, value, base: Path) -> Path | None:
    """Resolve a stored server path under ``root`` (mirrors the service loader)."""
    v = str(value or "").strip()
    if not v:
        return None
    p = Path(v)
    if p.is_absolute():
        try:
            rel = p.relative_to(base)
        except ValueError:
            return None
        return root / rel
    return root / p


def _restore_one(candidate: Path, target: Path, expected_sha: str) -> bool:
    """Copy candidate -> target only if candidate SHA == expected. Atomic, verified."""
    if len(expected_sha) != 64 or not candidate.is_file():
        return False
    if _sha256(candidate) != expected_sha:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        shutil.copyfile(candidate, tmp)
        if _sha256(tmp) != expected_sha:
            return False
        tmp.replace(target)
        return target.is_file() and _sha256(target) == expected_sha
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Restore SHA-verified truth-lock bytes from a fallback store."
    )
    ap.add_argument("--apply", action="store_true", help="write files (default: dry-run)")
    ap.add_argument("--dry-run", action="store_true", help="explicit no-op default")
    ap.add_argument("--fallback-root", default=str(DEFAULT_FALLBACK))
    args = ap.parse_args()

    base = Path(config.BASE_DIR)
    fallback = Path(args.fallback_root)
    db_path = Path(str(config.DB_PATH))
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== truth-lock byte repair ({mode}) ===")
    print(f"base_dir:      {base}")
    print(f"fallback_root: {fallback}  (exists={fallback.is_dir()})")
    print(f"db_path:       {db_path}")
    if not db_path.is_file():
        print("NO DB — nothing to do")
        return 1
    if not fallback.is_dir():
        print("FALLBACK ROOT MISSING — nothing to restore from")
        return 1

    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM product_visual_truth_lock").fetchall()

    total = len(rows)
    present = restorable_src = restorable_cut = restored_src = restored_cut = 0
    unrecoverable = 0
    for r in rows:
        d = dict(r)
        exp_s = str(d.get("canonical_sha256") or "").strip().lower()
        exp_c = str(d.get("canonical_cutout_sha256") or "").strip().lower()
        tgt_s = _resolve(base, d.get("canonical_source_path"), base)
        tgt_c = _resolve(base, d.get("canonical_cutout_path"), base)
        cand_s = _resolve(fallback, d.get("canonical_source_path"), base)
        cand_c = _resolve(fallback, d.get("canonical_cutout_path"), base)

        s_here = bool(tgt_s and tgt_s.is_file() and _sha256(tgt_s) == exp_s and len(exp_s) == 64)
        c_here = bool(tgt_c and tgt_c.is_file() and _sha256(tgt_c) == exp_c and len(exp_c) == 64)
        if s_here and c_here:
            present += 1
            continue

        s_can = bool(
            not s_here and cand_s and cand_s.is_file() and len(exp_s) == 64 and _sha256(cand_s) == exp_s
        )
        c_can = bool(
            not c_here and cand_c and cand_c.is_file() and len(exp_c) == 64 and _sha256(cand_c) == exp_c
        )
        if s_can:
            restorable_src += 1
            if args.apply and tgt_s and _restore_one(cand_s, tgt_s, exp_s):
                restored_src += 1
        if c_can:
            restorable_cut += 1
            if args.apply and tgt_c and _restore_one(cand_c, tgt_c, exp_c):
                restored_cut += 1
        if not (s_here or s_can) and not (c_here or c_can):
            unrecoverable += 1

    print(f"total rows:            {total}")
    print(f"already present:       {present}")
    print(f"restorable sources:    {restorable_src}")
    print(f"restorable cutouts:    {restorable_cut}")
    if args.apply:
        print(f"RESTORED sources:      {restored_src}")
        print(f"RESTORED cutouts:      {restored_cut}")
    print(f"neither recoverable:   {unrecoverable}")
    if not args.apply:
        print("\n(dry-run — re-run with --apply to write the restorable bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
