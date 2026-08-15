"""HTTP proof for the formula-native Copy Register V2 surface."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.copy_register_v2 import router
from agent.services import copy_register_v2_service as service
from tests.unit.test_copy_blueprint_v2_contract import _blueprint


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def test_register_exposes_all_eleven_lanes_and_exact_poster_paths():
    response = _client().get("/api/copy-register/v2/lanes")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 11
    poster = next(item for item in items if item["lane_id"] == "POSTER_BUILDER")
    assert poster["copy_policy"] == "REQUIRED"
    assert poster["adapter"] == "ImageCopyProjection"
    assert poster["current_api_entry_point"] == "POST /api/poster/compose and /api/poster/prompt-draft"
    assert {item["lane_id"] for item in items if item["media_kind"] == "VIDEO"} == {
        "T2V", "F2V", "HYBRID", "I2V", "FACELESS", "MONTAGE", "PRODUCTION_STUDIO_P6"
    }


def test_formula_catalog_has_no_default_or_hso_fallback():
    response = _client().get("/api/copy-register/v2/formulas")
    assert response.status_code == 200
    body = response.json()
    assert body["explicit_formula_required"] is True
    assert body["default_formula"] is None
    assert body["formulas"]
    assert all(item["formula_version"] for item in body["formulas"])


def test_text_assist_status_is_secret_free_and_zero_call(monkeypatch):
    monkeypatch.setattr(
        service.ai_provider,
        "provider_status",
        lambda: {
            "lane": "text_assist",
            "configured": True,
            "provider_id": "synthetic-test-provider",
            "model_id": "synthetic-test-model",
            "execution_enabled": True,
        },
    )
    response = _client().get("/api/copy-register/v2/provider-status")
    assert response.status_code == 200
    assert response.json() == {
        "lane": "text_assist",
        "status": "READY",
        "configured": True,
        "provider_id": "synthetic-test-provider",
        "model_id": "synthetic-test-model",
        "execution_enabled": True,
        "provider_calls": 0,
    }
    assert not {"api_key", "masked_key", "key_present"} & response.json().keys()


def test_blueprint_list_includes_persisted_activation_state(monkeypatch):
    async def fake_list(_product_id):
        return [_blueprint()]

    async def fake_activation(_product_id):
        return {
            "active_blueprint_id": "bp-001",
            "active_revision": 1,
            "active_lane_count": 8,
            "required_lane_count": 8,
            "activated_at": "2026-08-15T00:00:00Z",
        }

    monkeypatch.setattr(service, "list_blueprints", fake_list)
    monkeypatch.setattr(service, "get_activation_status", fake_activation)
    response = _client().get("/api/copy-register/v2/product/product-1/blueprints")
    assert response.status_code == 200
    expected = {
        "active_blueprint_id": "bp-001",
        "active_revision": 1,
        "active_lane_count": 8,
        "required_lane_count": 8,
        "activated_at": "2026-08-15T00:00:00Z",
    }
    assert response.json()["activation"] == expected
    assert response.json()["legacy_copy_rows_read"] == 0


def test_generate_unknown_formula_fails_closed_before_product_lookup():
    response = _client().post(
        "/api/copy-register/v2/blueprints/generate",
        json={
            "product_id": "missing-product",
            "formula_id": "UNKNOWN_FORMULA",
            "objective_id": "conversion",
            "objective_definition": "A grounded objective",
            "angle_id": "angle:missing",
            "angle_definition": "An angle",
            "evidence_fact_ids": ["fact:missing"],
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "COPY_V2_UNKNOWN_FORMULA"


def test_generate_requires_approved_product_truth():
    response = _client().post(
        "/api/copy-register/v2/blueprints/generate",
        json={
            "product_id": "missing-product",
            "formula_id": "PAS",
            "objective_id": "conversion",
            "objective_definition": "A grounded objective",
            "angle_id": "angle:missing",
            "angle_definition": "An angle",
            "evidence_fact_ids": ["fact:missing"],
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "PRODUCT_NOT_FOUND"


def test_generated_payload_is_v2_only_and_never_exposes_legacy_id(monkeypatch):
    async def fake_generate(**_kwargs):
        return _blueprint()

    monkeypatch.setattr(service, "generate_blueprint", fake_generate)
    response = _client().post(
        "/api/copy-register/v2/blueprints/generate",
        json={
            "product_id": "product-1",
            "formula_id": "PAS",
            "objective_id": "conversion",
            "objective_definition": "A grounded objective",
            "angle_id": "angle-1",
            "angle_definition": "A grounded angle",
            "evidence_fact_ids": ["fact-benefit-001"],
        },
    )
    assert response.status_code == 200
    payload = response.json()["blueprint"]
    assert payload["version"] == "2"
    assert payload["blueprint_id"] == "bp-001"
    assert "copy_set_id" not in payload
    assert response.json()["legacy_copy_rows_written"] == 0
