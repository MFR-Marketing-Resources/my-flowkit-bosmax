"""The historical AI Copy Assist route is explicitly closed by the V2 cutover."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.copy_sets import router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def test_ai_assist_is_disabled_without_provider_call():
    r = _client().post("/api/copy-sets/ai-assist", json={"product_id": "prod-1"})
    assert r.status_code == 410
    assert r.json()["detail"]["error"] == "LEGACY_COPY_GENERATION_DISABLED"


def test_ai_assist_disabled_is_independent_of_product_existence():
    r = _client().post("/api/copy-sets/ai-assist", json={"product_id": "x"})
    assert r.status_code == 410
    assert r.json()["detail"]["error"] == "LEGACY_COPY_GENERATION_DISABLED"


def test_ai_assist_candidate_count_validation():
    # candidate_count is bounded 1..3 by the request model.
    r = _client().post("/api/copy-sets/ai-assist", json={"product_id": "p", "candidate_count": 9})
    assert r.status_code == 422  # pydantic validation, service never called
