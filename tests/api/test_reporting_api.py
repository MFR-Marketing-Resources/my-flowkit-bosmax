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


def test_pi_quality_summary_is_an_exact_four_way_partition():
    response = _client().get(
        "/api/reporting/pi-quality",
        params={"lifecycle_status": "ALL"},
    )
    assert response.status_code == 200
    body = response.json()
    expected = {
        "FULLY_COMPLETE",
        "APPROVED_WITH_GOVERNED_ABSENCE",
        "LEGACY_APPROVED_INCOMPLETE",
        "MISSING_APPROVED_INTELLIGENCE",
    }
    assert set(body["classes"]) == expected
    assert sum(item["total"] for item in body["classes"].values()) == (
        body["total_real_products"])
    assert set(body["drill_down_kinds"].values()) == {
        "pi_fully_complete",
        "pi_governed_absence",
        "pi_legacy_incomplete",
        "pi_missing_approved",
    }


def test_all_pi_quality_drill_down_kinds_use_the_exception_contract():
    client = _client()
    for kind in (
        "pi_fully_complete",
        "pi_governed_absence",
        "pi_legacy_incomplete",
        "pi_missing_approved",
    ):
        response = client.get(
            "/api/reporting/exceptions",
            params={
                "kind": kind,
                "lifecycle_status": "ALL",
                "limit": 15,
                "offset": 0,
                "q": "nakamichi",
                "sort_by": "product_display_name",
                "sort_dir": "asc",
            },
        )
        assert response.status_code == 200, (kind, response.text)
        body = response.json()
        assert body["kind"] == kind
        assert body["limit"] == 15
        assert body["offset"] == 0
        assert "items" in body and "total" in body
