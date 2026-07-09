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
