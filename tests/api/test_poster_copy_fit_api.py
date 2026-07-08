from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.poster_prompt import router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def test_fit_endpoint_returns_service_shape(monkeypatch):
    from agent.models.poster_copy_fit import (
        PosterCopyFitFields,
        PosterCopyFitResponse,
    )

    def fake_fit(_body):
        return PosterCopyFitResponse(
            applied=True,
            provider_configured=True,
            fields=PosterCopyFitFields(hook="Short hook", cta="Beli"),
            changed_fields=["Hook"],
            still_over_limit=[],
            warnings=[],
        )

    monkeypatch.setattr("agent.api.poster_prompt.fit_poster_copy", fake_fit)

    response = _client().post(
        "/api/poster/copy/fit",
        json={"language": "ms", "hook": "x" * 90, "cta": "y" * 40},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["applied"] is True
    assert body["fields"]["hook"] == "Short hook"
    assert body["changed_fields"] == ["Hook"]


def test_fit_endpoint_defaults_are_optional():
    # Empty copy is valid input (nothing over limit) — the route must accept it.
    response = _client().post("/api/poster/copy/fit", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["applied"] is False
    assert "provider_configured" in body
