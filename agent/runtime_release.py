"""Production runtime provenance lock.

Prevents the recurring incident where ``:8100`` is served directly from the
mutable development checkout (``C:\\Users\\USER\\Desktop\\_ref_flowkit``) on a
stale branch with uncommitted WIP — which made the browser receive a stale
dashboard bundle (e.g. missing the Visual / Canva tab) even though canonical
``main`` was correct.

Contract: production launches ONLY from an immutable RELEASE directory
(``_bosmax_runtime/releases/<sha>``), pinned by a ``current`` pointer, carrying a
``runtime_manifest.json`` whose ``deployed_sha`` matches the release's git HEAD
and whose ``dashboard_bundle`` matches the built SPA. The canonical mutable DB
stays EXTERNAL at the dev root (code and mutable data are separate). The launcher
FAILS CLOSED — never silently serves stale source — if any invariant is violated.

This module is pure/inspectable so both the launcher (fail-closed startup) and
the health API (live diagnostics) share one source of truth.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

MANIFEST_FILENAME = "runtime_manifest.json"

# ── Fail-closed error codes (stable; asserted by tests + surfaced by launcher) ──
ERR_DEV_ROOT = "PRODUCTION_RUNTIME_DEV_ROOT_FORBIDDEN"
ERR_MANIFEST_MISSING = "PRODUCTION_RUNTIME_MANIFEST_MISSING"
ERR_SHA_UNRESOLVABLE = "PRODUCTION_RUNTIME_SHA_UNRESOLVABLE"
ERR_DIRTY = "PRODUCTION_RUNTIME_DIRTY"
ERR_SHA_MISMATCH = "PRODUCTION_RUNTIME_SHA_MISMATCH"
ERR_DB_PATH = "PRODUCTION_DB_PATH_MISMATCH"
ERR_BUNDLE = "PRODUCTION_BUNDLE_MISMATCH"
ERR_FILES_MISSING = "PRODUCTION_RUNTIME_FILES_MISSING"

# Files a valid release must contain (relative to the release root).
REQUIRED_RELEASE_FILES = ("agent/main.py", "dashboard/dist/index.html")


def dev_root() -> Path:
    return Path(os.environ.get("BOSMAX_DEV_ROOT", r"C:/Users/USER/Desktop/_ref_flowkit")).resolve()


def canonical_db_path() -> Path:
    return Path(os.environ.get("BOSMAX_CANONICAL_DB", str(dev_root() / "flow_agent.db"))).resolve()


def source_root() -> Path:
    """Return the immutable code/assets root without importing an API module."""
    return Path(__file__).resolve().parent.parent


# ── git helpers (module-level so tests can monkeypatch) ──────────────────────
def _git(source_root: Path, *args: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=str(source_root), stderr=subprocess.DEVNULL, text=True, timeout=8
        ).strip()
    except Exception:
        return None


def git_output(*args: str) -> str | None:
    """Read git provenance from the served source root, with no app side effects."""
    return _git(source_root(), *args)


def git_head(source_root) -> str | None:
    return _git(Path(source_root), "rev-parse", "HEAD") or None


def git_is_dirty(source_root) -> bool | None:
    """True if the release tree has UNEXPECTED changes.

    The deploy artifacts a release legitimately carries — ``runtime_manifest.json``
    (stamped at deploy) and the gitignored ``dashboard/dist`` / ``node_modules`` —
    are not "dirt". ``git status --porcelain`` already omits gitignored paths; we
    additionally filter the manifest so a correctly deployed release reads clean.
    """
    out = _git(Path(source_root), "status", "--porcelain")
    if out is None:
        return None
    real = [ln for ln in out.splitlines() if ln.strip() and MANIFEST_FILENAME not in ln]
    return bool(real)


def served_dashboard_bundle(source_root) -> str | None:
    import re

    try:
        html = (Path(source_root) / "dashboard" / "dist" / "index.html").read_text(encoding="utf-8")
        m = re.search(r"assets/(index-[\w-]+\.js)", html)
        return m.group(1) if m else None
    except Exception:
        return None


# ── runtime manifest ─────────────────────────────────────────────────────────
@dataclass
class RuntimeManifest:
    deployed_sha: str
    deployed_at: str
    release_dir: str
    dashboard_bundle: str | None
    db_path: str
    schema: str = "bosmax-runtime-manifest/1"
    config_version: str | None = None


def manifest_path(source_root) -> Path:
    return Path(source_root) / MANIFEST_FILENAME


def read_manifest(source_root) -> dict | None:
    p = manifest_path(source_root)
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None
    except Exception:
        return None


def write_manifest(source_root, *, deployed_sha, deployed_at, dashboard_bundle, db_path, config_version=None) -> dict:
    manifest = RuntimeManifest(
        deployed_sha=deployed_sha,
        deployed_at=deployed_at,
        release_dir=str(Path(source_root).resolve()),
        dashboard_bundle=dashboard_bundle,
        db_path=str(Path(db_path).resolve()),
        config_version=config_version,
    )
    data = asdict(manifest)
    manifest_path(source_root).write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    return data


def _required_files_present(source_root) -> bool:
    root = Path(source_root)
    return all((root / rel).is_file() for rel in REQUIRED_RELEASE_FILES)


# ── provenance resolution (shared by launcher + health API) ──────────────────
def resolve_provenance(source_root, db_path, *, origin_main: str | None = None) -> dict:
    root = Path(source_root).resolve()
    dev = dev_root()
    manifest = read_manifest(root)
    head = git_head(root)
    dirty = git_is_dirty(root)
    bundle = served_dashboard_bundle(root)
    deployment_sha = (manifest or {}).get("deployed_sha")

    dev_root_serving = root == dev
    db_canonical = Path(db_path).resolve() == canonical_db_path()
    bundle_matches = manifest is None or manifest.get("dashboard_bundle") == bundle
    sha_matches_manifest = bool(deployment_sha and head and deployment_sha == head)

    canonical_runtime = bool(
        (not dev_root_serving)
        and manifest is not None
        and sha_matches_manifest
        and dirty is False
        and db_canonical
        and bundle_matches
        and _required_files_present(root)
    )
    source_stale = (not canonical_runtime) or bool(
        origin_main and head and head != origin_main
    )

    return {
        "runtime_sha": head,
        "deployment_sha": deployment_sha,
        "release_dir": str(root),
        "dev_root": str(dev),
        "dev_root_serving_production": dev_root_serving,
        "db_path": str(Path(db_path).resolve()),
        "db_canonical": db_canonical,
        "dashboard_bundle": bundle,
        "bundle_matches": bundle_matches,
        "release_dirty": dirty,
        "sha_matches_manifest": sha_matches_manifest,
        "manifest_present": manifest is not None,
        "required_files_present": _required_files_present(root),
        "canonical_runtime": canonical_runtime,
        "source_stale": source_stale,
    }


def validate_production_release(source_root, db_path) -> tuple[bool, str | None, dict]:
    """Fail-closed gate for the production launcher. Returns (ok, error_code, provenance).

    Checks run most-dangerous-first so the returned code names the real cause.
    """
    p = resolve_provenance(source_root, db_path)
    if p["dev_root_serving_production"]:
        return False, ERR_DEV_ROOT, p
    if not p["required_files_present"]:
        return False, ERR_FILES_MISSING, p
    if not p["manifest_present"]:
        return False, ERR_MANIFEST_MISSING, p
    if p["runtime_sha"] is None:
        return False, ERR_SHA_UNRESOLVABLE, p
    if p["release_dirty"]:
        return False, ERR_DIRTY, p
    if not p["sha_matches_manifest"]:
        return False, ERR_SHA_MISMATCH, p
    if not p["db_canonical"]:
        return False, ERR_DB_PATH, p
    if not p["bundle_matches"]:
        return False, ERR_BUNDLE, p
    return True, None, p


def _main(argv) -> int:
    """CLI used by the PowerShell launcher/deployer so PS and the API share ONE
    provenance source of truth. Exit 0 = ok, non-zero = fail-closed."""
    import argparse

    parser = argparse.ArgumentParser(prog="agent.runtime_release")
    sub = parser.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", help="fail-closed production gate")
    v.add_argument("release_dir")
    v.add_argument("--db", default=str(canonical_db_path()))
    w = sub.add_parser("write-manifest", help="stamp runtime_manifest.json into a release")
    w.add_argument("release_dir")
    w.add_argument("--sha", required=True)
    w.add_argument("--at", required=True)
    w.add_argument("--db", default=str(canonical_db_path()))
    pr = sub.add_parser("provenance", help="print resolved provenance")
    pr.add_argument("release_dir")
    pr.add_argument("--db", default=str(canonical_db_path()))
    args = parser.parse_args(argv)

    if args.cmd == "validate":
        ok, code, prov = validate_production_release(args.release_dir, args.db)
        print(json.dumps({"ok": ok, "error_code": code, "provenance": prov}, indent=2))
        return 0 if ok else 1
    if args.cmd == "write-manifest":
        bundle = served_dashboard_bundle(args.release_dir)
        data = write_manifest(
            args.release_dir, deployed_sha=args.sha, deployed_at=args.at,
            dashboard_bundle=bundle, db_path=args.db,
        )
        print(json.dumps(data, indent=2))
        return 0
    if args.cmd == "provenance":
        print(json.dumps(resolve_provenance(args.release_dir, args.db), indent=2))
        return 0
    return 2


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv[1:]))
