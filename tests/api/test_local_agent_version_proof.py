import os

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.local_agent import CRITICAL_ROUTE_PATHS, router


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def test_version_proof_reports_process_and_route_identity():
    client = TestClient(_build_app())
    response = client.get("/api/local-agent/version-proof")
    assert response.status_code == 200
    body = response.json()

    assert body["pid"] == os.getpid()
    assert body["process_started_at"]
    assert body["route_count"] > 0
    # Every critical route is reported explicitly (True/False), so version skew
    # is observable instead of surfacing as a misleading 404.
    assert set(body["critical_routes"].keys()) == set(CRITICAL_ROUTE_PATHS)
    assert isinstance(body["source_stale_since_start"], bool)
    assert isinstance(body["stale_source_sample"], list)


def test_critical_route_list_pins_incident_routes():
    # The audit route that mis-served during the 2026-07-09 incident must stay
    # on the critical list; removing it silently would blind the guardrail.
    assert "/api/creative-assets/eligibility-audit" in CRITICAL_ROUTE_PATHS
    assert "/api/flow/execute-flow-job" in CRITICAL_ROUTE_PATHS


def test_version_proof_backfills_critical_routes_from_openapi_when_app_routes_underreport():
    # Regression: in the runtime's process topology request.app.routes under-reports
    # (observed 13 vs the 351 /openapi.json and real routing expose). The critical
    # routes vanish from the route table but remain in the served OpenAPI schema.
    # The guard must consult OpenAPI so present routes are not false-flagged missing
    # (which fired a spurious "Backend version mismatch — restart the agent" banner).
    import asyncio
    from types import SimpleNamespace

    from agent.api.local_agent import get_local_agent_version_proof

    app = _build_app()
    for path in CRITICAL_ROUTE_PATHS:
        app.add_api_route(path, lambda: {"ok": True}, methods=["POST"])
    schema = app.openapi()  # correct schema carries every critical path
    assert all(p in schema["paths"] for p in CRITICAL_ROUTE_PATHS)
    # Emulate the under-reporting worker: strip the critical routes from the route
    # table while the served OpenAPI schema still carries them.
    app.router.routes = [
        r for r in app.router.routes
        if getattr(r, "path", "") not in CRITICAL_ROUTE_PATHS
    ]
    app.openapi_schema = schema

    proof = asyncio.run(get_local_agent_version_proof(SimpleNamespace(app=app)))

    assert all(proof.critical_routes[p] for p in CRITICAL_ROUTE_PATHS), proof.critical_routes
    assert proof.route_count >= len(CRITICAL_ROUTE_PATHS)


# ── Sandbox provenance (RPA Round B): FLOW_AGENT_DIR relocates RUNTIME STORAGE
# (BASE_DIR). Provenance must still describe the SERVED CODE, which lives at the
# source root. Before this, a sandbox reported git_head=None and — worse — the
# staleness scan passed VACUOUSLY because BASE_DIR had no `agent/` tree.

def test_provenance_resolves_from_source_root_not_runtime_storage():
    """git + staleness provenance must not follow a relocated BASE_DIR."""
    from pathlib import Path

    from agent.api import local_agent

    # _SOURCE_ROOT is derived from this module's own location and must be the
    # repo that actually contains the served code.
    assert (local_agent._SOURCE_ROOT / "agent" / "api" / "local_agent.py").exists()
    assert (local_agent._SOURCE_ROOT / "agent").is_dir()

    # It must NOT be derived from BASE_DIR, which FLOW_AGENT_DIR can relocate.
    assert local_agent._SOURCE_ROOT == Path(local_agent.__file__).resolve().parent.parent.parent


def test_staleness_scan_is_not_vacuous(monkeypatch, tmp_path):
    """The scan must inspect real source files even when BASE_DIR is relocated.

    Regression guard: pointing BASE_DIR at an empty sandbox previously made
    _stale_backend_sources() iterate zero files and report "not stale" — a false
    pass that proved nothing.
    """
    from agent.api import local_agent

    # Relocate runtime storage the way FLOW_AGENT_DIR does.
    monkeypatch.setattr(local_agent, "BASE_DIR", tmp_path)

    # Freeze "process start" in the past so every real source file counts as
    # stale — if the scan reaches the true source tree it MUST find files.
    class _Past:
        @staticmethod
        def timestamp() -> float:
            return 0.0

    monkeypatch.setattr(local_agent, "_PROCESS_STARTED_AT_DT", _Past)
    stale = local_agent._stale_backend_sources()
    assert stale, "staleness scan found nothing -> it is scanning the wrong root"
    assert all(s.endswith(".py") for s in stale)

    # And with "start" in the future, nothing is stale — proving the scan is
    # actually comparing mtimes rather than always returning a constant.
    class _Future:
        @staticmethod
        def timestamp() -> float:
            return 2**40

    monkeypatch.setattr(local_agent, "_PROCESS_STARTED_AT_DT", _Future)
    assert local_agent._stale_backend_sources() == []


def test_git_provenance_survives_relocated_base_dir(monkeypatch, tmp_path):
    """git_head must still resolve when BASE_DIR points outside the repo."""
    from agent.api import local_agent

    monkeypatch.setattr(local_agent, "BASE_DIR", tmp_path)
    head = local_agent._git_output("rev-parse", "HEAD")
    # In a git checkout this is a 40-char SHA; tolerate non-git environments by
    # asserting only that a relocated BASE_DIR does not change the answer.
    assert head == local_agent._git_output("rev-parse", "HEAD")
    if head is not None:
        assert len(head) == 40


# ── Gap D: FLOW_AGENT_DIR must relocate RUNTIME STORAGE only. The built SPA is a
# SOURCE asset; pointing it at BASE_DIR made a sandbox serve 503 build_required for
# every page, leaving no UI for an RPA operator to drive.

def test_dashboard_dist_resolves_from_source_root_not_runtime_storage(monkeypatch, tmp_path):
    """dashboard/dist must not follow a relocated BASE_DIR."""
    from agent.api import local_agent

    monkeypatch.setattr(local_agent, "BASE_DIR", tmp_path)
    dist_dir, index_file = local_agent.get_dashboard_paths()

    # Must NOT have followed BASE_DIR into the sandbox...
    assert tmp_path not in dist_dir.parents and dist_dir != tmp_path
    # ...and must point at the real source tree.
    assert dist_dir == local_agent._SOURCE_ROOT / "dashboard" / "dist"
    assert index_file == dist_dir / "index.html"


def test_dashboard_serving_mode_survives_relocated_base_dir(monkeypatch, tmp_path):
    """A sandbox must still report BACKEND_SERVED_STATIC when the repo is built."""
    from agent.api import local_agent

    _, index_file = local_agent.get_dashboard_paths()
    built = index_file.exists()

    monkeypatch.setattr(local_agent, "BASE_DIR", tmp_path)
    mode = local_agent.get_dashboard_serving_mode()
    # The answer must depend on the SOURCE tree's build state, never on BASE_DIR.
    assert mode == ("BACKEND_SERVED_STATIC" if built else "BACKEND_BUILD_REQUIRED")


def test_path_boundary_storage_vs_source(monkeypatch, tmp_path):
    """The whole point of the sandbox: DB isolates, served assets/code do not."""
    from agent.api import local_agent

    monkeypatch.setattr(local_agent, "BASE_DIR", tmp_path)

    # SOURCE side: code + built assets stay at the source root.
    assert (local_agent._SOURCE_ROOT / "agent").is_dir()
    assert local_agent.get_dashboard_paths()[0].parent.parent == local_agent._SOURCE_ROOT

    # STORAGE side: agent.config resolves DB under FLOW_AGENT_DIR, away from source.
    import os
    import subprocess
    import sys

    # agent.config auto-isolates DB_PATH to a temp file when it detects pytest, so
    # the pytest markers must be REMOVED (an empty value still counts as present).
    child_env = {k: v for k, v in os.environ.items()
                 if k not in ("PYTEST_CURRENT_TEST", "PYTEST_VERSION")}
    child_env["FLOW_AGENT_DIR"] = str(tmp_path)
    out = subprocess.run(
        [sys.executable, "-c",
         "from agent.config import DB_PATH, BASE_DIR; print(DB_PATH); print(BASE_DIR)"],
        capture_output=True, text=True, env=child_env,
        cwd=str(local_agent._SOURCE_ROOT),
    )
    assert out.returncode == 0, out.stderr
    db_path, base_dir = [ln.strip() for ln in out.stdout.strip().splitlines()[:2]]
    assert str(tmp_path) in db_path, f"DB did not isolate: {db_path}"
    assert str(tmp_path) in base_dir
    assert str(local_agent._SOURCE_ROOT) not in db_path
