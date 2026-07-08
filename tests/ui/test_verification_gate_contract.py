"""Contract for the local verification gate (scripts/verify-gate.ps1).

Guards the load-bearing property: the gate must run the REAL dashboard build
(`npm run build` = `tsc -b && vite build`) — not a weaker `tsc --noEmit` proxy — plus
vitest, a backend pytest smoke, and mandor-check, and must label itself LOCAL-ONLY.
This is the regression guard for the PR #265/#266 build-verification gap.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_verify_gate_script_exists():
    assert (ROOT / "scripts/verify-gate.ps1").exists()


def test_verify_gate_runs_the_real_build_and_all_layers():
    gate = _read("scripts/verify-gate.ps1")
    # The load-bearing gate: the REAL production build (npm run build = tsc -b && vite
    # build), not the weaker `tsc --noEmit` proxy that missed the PR #265 regression.
    assert "npm run build" in gate
    # Every required layer is present.
    assert "DASHBOARD_BUILD" in gate
    assert "DASHBOARD_VITEST" in gate
    assert "npm test" in gate
    assert "pytest" in gate
    assert "mandor-check.ts" in gate


def test_verify_gate_fails_closed_and_is_labeled_local_only():
    gate = _read("scripts/verify-gate.ps1")
    # Fail-closed: any FAIL => non-zero exit (so a broken build blocks "green").
    assert "exit 1" in gate
    assert "GATE RESULT: FAIL" in gate
    # Honest scope: never claim CI.
    assert "LOCAL ONLY" in gate


def test_verify_gate_backend_smoke_set_is_curated_and_stable():
    gate = _read("scripts/verify-gate.ps1")
    # A representative, stable suite must be in the curated smoke set.
    assert "tests/unit/test_copyset_approval_formula_gate.py" in gate
    assert "tests/unit/test_claim_boundary.py" in gate


def test_dashboard_verify_script_wired():
    pkg = _read("dashboard/package.json")
    assert '"build": "tsc -b && vite build"' in pkg
    assert '"verify"' in pkg


def test_verification_gate_is_documented():
    doc = _read("docs/VERIFICATION_GATE.md")
    assert "verify-gate.ps1" in doc
    assert "LOCAL ONLY" in doc
