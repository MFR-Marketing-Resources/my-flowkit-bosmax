"""API contract tests for the Command Centre reporting router (read-only).

The aggregation math is covered by tests/unit/test_reporting_service.py; here we only
assert the router wiring: valid kinds return 200 with the right shape, an unknown kind
is rejected 422, and the coverage endpoints answer safely on an empty DB.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.reporting import router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_unknown_exception_kind_is_422():
    r = _client().get("/api/reporting/exceptions", params={"kind": "bogus"})
    assert r.status_code == 422
    assert "UNKNOWN_EXCEPTION_KIND" in r.json()["detail"]


def test_coverage_endpoints_are_shaped_on_empty_db():
    c = _client()
    for path in (
        "/api/reporting/coverage/copywriting",
        "/api/reporting/coverage/product-intelligence",
        "/api/reporting/coverage/prompt-readiness",
    ):
        r = c.get(path)
        assert r.status_code == 200, path
        assert "total_products" in r.json(), path


def test_exceptions_valid_kind_returns_list_shape():
    r = _client().get("/api/reporting/exceptions", params={"kind": "missing_copy"})
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "missing_copy"
    assert "items" in body and "total" in body and "limit" in body


def test_exceptions_limit_is_bounded():
    # limit above the ceiling is a 422 (FastAPI Query le=500)
    r = _client().get("/api/reporting/exceptions", params={"kind": "missing_copy", "limit": 9999})
    assert r.status_code == 422
