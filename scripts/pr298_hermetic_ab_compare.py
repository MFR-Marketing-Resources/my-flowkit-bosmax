"""Hermetic A/B backend comparison for PR #298 (machine-verifiable evidence)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from tests.support.hermetic_runtime import (  # noqa: E402
    fixture_hash,
    hermetic_env_for_root,
    install_hermetic_runtime_root,
    manifest_payload,
)

CANONICAL_ROOT = Path(os.environ.get("PR298_CANONICAL_GUARD_PATH", r"C:/Users/USER/Desktop/_ref_flowkit"))


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_guard_snapshot() -> dict:
    settings = CANONICAL_ROOT / ".local-agent" / "ai-provider-settings.json"
    return {
        "canonical_root": str(CANONICAL_ROOT),
        "ai_provider_settings_sha256": _sha256_file(settings),
        "note": "snapshot_only_no_mutation",
    }


def git_rev(repo: Path) -> str:
    out = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True)
    return out.strip()


def parse_junit_failures(junit_path: Path) -> list[dict]:
    if not junit_path.is_file():
        return []
    root = ET.parse(junit_path).getroot()
    failures: list[dict] = []
    for case in root.iter("testcase"):
        if case.find("failure") is None and case.find("error") is None:
            continue
        classname = case.get("classname") or ""
        name = case.get("name") or ""
        file_attr = case.get("file") or ""
        if file_attr and name:
            nodeid = f"{file_attr}::{name}"
        elif classname and name:
            nodeid = f"{classname.replace('.', '/')}.py::{name}".replace("/py.py", ".py")
        else:
            nodeid = name or classname
        fail_el = case.find("failure") or case.find("error")
        msg = (fail_el.get("message") if fail_el is not None else "") or ""
        text = (fail_el.text or "") if fail_el is not None else ""
        failures.append(
            {
                "nodeid": nodeid,
                "classname": classname,
                "name": name,
                "message": msg[:500],
                "signature": hashlib.sha256((msg + text).encode("utf-8", errors="replace")).hexdigest()[:24],
            }
        )
    return failures


def run_pytest_suite(
    *,
    label: str,
    repo: Path,
    python_exe: Path,
    agent_root: Path,
    junit_out: Path,
) -> dict:
    env = hermetic_env_for_root(agent_root, repo_for_pythonpath=repo)
    cmd = [
        str(python_exe),
        "-m",
        "pytest",
        "tests/unit",
        "tests/ui",
        "tests/api",
        "-q",
        "--tb=no",
        f"--junitxml={junit_out}",
    ]
    started = datetime.now(timezone.utc).isoformat()
    proc = subprocess.run(cmd, cwd=repo, env=env, capture_output=True, text=True)
    ended = datetime.now(timezone.utc).isoformat()
    summary_line = ""
    for line in reversed((proc.stdout or "").splitlines()):
        if "passed" in line or "failed" in line or "error" in line:
            summary_line = line.strip()
            break
    failures = parse_junit_failures(junit_out)
    return {
        "label": label,
        "commit_sha": git_rev(repo),
        "exit_code": proc.returncode,
        "summary_line": summary_line,
        "failure_count": len(failures),
        "failures": failures,
        "started_at": started,
        "ended_at": ended,
        "stdout_tail": (proc.stdout or "")[-4000:],
        "stderr_tail": (proc.stderr or "")[-2000:],
        "manifest": manifest_payload(
            label=label,
            commit_sha=git_rev(repo),
            python_executable=str(python_exe),
            python_version=subprocess.check_output([str(python_exe), "--version"], text=True).strip(),
            cwd=str(repo),
            agent_root=str(agent_root),
            test_command=cmd,
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--main-repo", type=Path, required=True)
    parser.add_argument("--branch-repo", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, default=None)
    args = parser.parse_args()

    evidence_dir = args.evidence_dir or Path(tempfile.gettempdir()) / "pr298-ab-evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    guard_before = canonical_guard_snapshot()
    main_root = install_hermetic_runtime_root(evidence_dir / "pr298-main-state")
    branch_root = install_hermetic_runtime_root(evidence_dir / "pr298-branch-state")

    main_result = run_pytest_suite(
        label="origin_main",
        repo=args.main_repo.resolve(),
        python_exe=args.python.resolve(),
        agent_root=main_root,
        junit_out=evidence_dir / "junit_main.xml",
    )
    branch_result = run_pytest_suite(
        label="pr298_branch",
        repo=args.branch_repo.resolve(),
        python_exe=args.python.resolve(),
        agent_root=branch_root,
        junit_out=evidence_dir / "junit_branch.xml",
    )
    guard_after = canonical_guard_snapshot()

    main_ids = {f["nodeid"]: f for f in main_result["failures"]}
    branch_ids = {f["nodeid"]: f for f in branch_result["failures"]}
    added = sorted(set(branch_ids) - set(main_ids))
    removed = sorted(set(main_ids) - set(branch_ids))
    unchanged = sorted(set(main_ids) & set(branch_ids))

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fixture_hash": fixture_hash(),
        "canonical_guard_before": guard_before,
        "canonical_guard_after": guard_after,
        "canonical_guard_unchanged": guard_before == guard_after,
        "main": main_result,
        "branch": branch_result,
        "comparison": {
            "main_failure_ids": sorted(main_ids.keys()),
            "branch_failure_ids": sorted(branch_ids.keys()),
            "added_failures": [branch_ids[i] for i in added],
            "removed_failures": [main_ids[i] for i in removed],
            "unchanged_failures": [main_ids[i] for i in unchanged],
            "net_new_failures": added,
        },
    }
    out_json = evidence_dir / "pr298_ab_summary.json"
    out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["comparison"], indent=2))
    print(f"evidence={out_json}")
    return 0 if not added else 2


if __name__ == "__main__":
    raise SystemExit(main())