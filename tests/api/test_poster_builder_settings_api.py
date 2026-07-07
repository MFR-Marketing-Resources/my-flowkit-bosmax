"""API tests for GET /api/poster/builder-settings."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.poster_prompt import router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def test_builder_settings_get_returns_dimensions():
    response = _client().get("/api/poster/builder-settings")
    assert response.status_code == 200
    body = response.json()
    for dim in (
        "poster_objectives",
        "poster_types",
        "languages",
        "visual_routes",
        "human_presence_modes",
        "text_density_options",
    ):
        assert dim in body and len(body[dim]) >= 2
    labels = [o["label"] for o in body["poster_objectives"]]
    assert "Product awareness" in labels


def test_builder_settings_flow_mirror_and_models():
    body = _client().get("/api/poster/builder-settings").json()
    fm = body["flow_mirror"]
    for ratio in ("9:16", "1:1", "16:9", "4:3", "3:4"):
        assert ratio in fm["aspect_ratios"]
    assert fm["counts"] == [1, 2, 3, 4]
    model_labels = [m["label"] for m in fm["image_models"]]
    assert "Nano Banana 2" in model_labels
    assert fm["defaults"]["aspect_ratio"] == "9:16"


def test_builder_settings_copy_and_ai_sections():
    body = _client().get("/api/poster/builder-settings").json()
    assert "DIRECT" in body["copy_components"]["routes"]
    assert body["ai_provider"]["lane"] == "text_assist"
    assert body["ai_provider"]["status"] in ("configured", "unavailable")
    assert "sources" in body


def test_builder_settings_is_get_only_post_405():
    """The route is GET; a POST must 405 (guards against method drift)."""
    response = _client().post("/api/poster/builder-settings", json={})
    assert response.status_code == 405
