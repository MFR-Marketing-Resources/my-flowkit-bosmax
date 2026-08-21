from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.production_output_reporting import router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_production_summary_is_read_only_and_shaped_on_empty_ledgers():
    response = _client().get(
        "/api/reporting/production",
        params={"start_date": "2026-08-01", "end_date": "2026-08-01"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reporting_timezone"] == "Asia/Kuala_Lumpur"
    assert body["overview"]["total_attempts"] == 0
    assert body["overview"]["success_rate"] is None
    assert body["filters"]["production_recipes"] == ["HYBRID", "FACELESS", "MONTAGE", "POSTER_BUILDER"]
    assert body["filters"]["origin_surfaces"] == ["PRODUCTION_STUDIO", "STANDALONE", "POSTER_BUILDER"]


def test_production_ledger_is_paginated_and_rejects_internal_recipe_filters():
    client = _client()
    response = client.get(
        "/api/reporting/production/ledger",
        params={"start_date": "2026-08-01", "end_date": "2026-08-01", "limit": 1, "offset": 0},
    )
    assert response.status_code == 200
    assert response.json()["limit"] == 1
    assert response.json()["items"] == []

    rejected = client.get(
        "/api/reporting/production",
        params={"production_recipe": "T2V"},
    )
    assert rejected.status_code == 422
