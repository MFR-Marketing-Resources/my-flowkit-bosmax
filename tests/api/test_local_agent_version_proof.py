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
