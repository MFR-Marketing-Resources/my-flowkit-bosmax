"""Faceless execution identity is checked before any provider-adjacent work."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.flow import router as flow_router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(flow_router, prefix="/api")
    return TestClient(app)


def _identity() -> dict[str, object]:
    return {
        "identity_version": "FACELESS_EXECUTION_IDENTITY_V1",
        "lane": "FACELESS",
        "transport_mode": "F2V",
        "product_id": "p1",
        "actor_profile_resolved": "FEMALE",
        "opening_strategy_resolved": "GENERAL_USP_PRODUCT",
    }


def test_generate_rejects_missing_faceless_identity_before_copy_resolution(
    monkeypatch,
) -> None:
    expected = _identity()
    monkeypatch.setattr(
        "agent.api.flow.crud.get_workspace_execution_package",
        AsyncMock(
            return_value={
                "request_lineage_payload": json.dumps(
                    {"faceless_execution_identity": expected}
                )
            }
        ),
    )

    response = _client().post(
        "/api/flow/generate",
        json={
            "mode": "F2V",
            "prompt": "provider-ready faceless prompt",
            "product_id": "p1",
            "source_mode": "HYBRID",
            "production_recipe": "FACELESS",
            "staff_id": "staff_pytest_operator",
            "workspace_execution_package_id": "wep_1",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == (
        "FACELESS_EXECUTION_IDENTITY_REQUIRED"
    )


def test_generate_rejects_mutated_faceless_identity_before_copy_resolution(
    monkeypatch,
) -> None:
    expected = _identity()
    monkeypatch.setattr(
        "agent.api.flow.crud.get_workspace_execution_package",
        AsyncMock(
            return_value={
                "request_lineage_payload": json.dumps(
                    {"faceless_execution_identity": expected}
                )
            }
        ),
    )

    response = _client().post(
        "/api/flow/generate",
        json={
            "mode": "F2V",
            "prompt": "provider-ready faceless prompt",
            "product_id": "p1",
            "source_mode": "HYBRID",
            "production_recipe": "FACELESS",
            "staff_id": "staff_pytest_operator",
            "workspace_execution_package_id": "wep_1",
            "execution_identity": {
                **expected,
                "actor_profile_resolved": "MALE",
            },
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == (
        "FACELESS_EXECUTION_IDENTITY_MISMATCH"
    )
