"""HTTP contract tests for the additive, read-only Phase 2 V2 surface."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.copy_architecture_v2 import router
from agent.models.copy_blueprint_v2 import EvidenceRegistry
from agent.services.copy_blueprint_v2_service import approve_copy_blueprint_v2
from tests.unit.test_copy_blueprint_v2_contract import _blueprint, _flags, _lineage, _fact


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def _payload(blueprint, *, approved=False, flags=None):
    body = {
        "blueprint": blueprint.model_dump(mode="json"),
        "current_product_truth": _lineage().model_dump(mode="json"),
        "evidence_facts": [_fact().model_dump(mode="json")],
    }
    if approved:
        body["require_approval"] = True
    if flags is not None:
        body["feature_flags"] = flags.model_dump(mode="json")
    return body


def _approved():
    return approve_copy_blueprint_v2(
        _blueprint(),
        approved_by="operator-1",
        current_product_truth=_lineage(),
        evidence_registry=EvidenceRegistry(facts=(_fact(),)),
        approved_at="2026-08-14T01:00:00Z",
    )


def test_lane_matrix_endpoint_returns_all_eleven_lanes():
    response = _client().get("/api/copy-architecture/v2/lanes")
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "2"
    assert len(body["items"]) == 11
    assert {row["copy_policy"] for row in body["items"]} == {"REQUIRED", "NOT_REQUIRED"}


def test_consumer_status_is_read_only_and_provider_free():
    response = _client().get("/api/copy-architecture/v2/consumer-status")
    assert response.status_code == 200
    body = response.json()
    assert body["feature_flags"]["state"] == "OFF"
    assert body["legacy_path_unchanged"] is True
    assert body["provider_calls"] == 0
    assert body["credit_spend"] is False


def test_validate_endpoint_is_read_only_and_exposes_production_gate():
    response = _client().post("/api/copy-architecture/v2/validate", json=_payload(_blueprint()))
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["production_valid"] is False
    assert body["error_codes"] == []


def test_validate_endpoint_fails_closed_for_unknown_formula():
    blueprint = _blueprint(formula_id="UNKNOWN_FORMULA", formula_version="unknown")
    response = _client().post("/api/copy-architecture/v2/validate", json=_payload(blueprint))
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert "COPY_V2_UNKNOWN_FORMULA" in body["error_codes"]


def test_bind_endpoint_requires_explicit_feature_flag_and_approval():
    disabled = _client().post(
        "/api/copy-architecture/v2/bind",
        json={**_payload(_approved(), approved=True), "lane": "T2V"},
    )
    assert disabled.status_code == 409
    assert disabled.json()["detail"]["error"] == "COPY_V2_FEATURE_FLAG_OFF"

    enabled = _client().post(
        "/api/copy-architecture/v2/bind",
        json={
            **_payload(_approved(), approved=True, flags=_flags()),
            "lane": "T2V",
        },
    )
    assert enabled.status_code == 200
    binding = enabled.json()["binding"]
    assert binding["blueprint_id"] == "bp-001"
    assert binding["revision"] == 1
    assert binding["formula_id"] == "PAS"
    assert binding["feature_flag_state"]["state"] == "PILOT"
