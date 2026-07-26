from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.scene_context_registry import router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def test_cluster_coverage_api_exposes_deterministic_read_only_contract():
    response = _client().get("/api/workspace/scene-context-registry/cluster-coverage")
    assert response.status_code == 200
    body = response.json()
    assert body["canonical_clusters"] == [
        "Automotive", "Baby & Kids", "Beauty", "Electronics & Gadgets", "Fashion",
        "Food & Beverage", "Home & Living", "Islamic & Books", "Office & Stationery",
        "Pet Care", "Sports & Outdoors", "Tools & Home Improvement",
    ]
    assert (body["active_scene_total"], body["classified_scene_total"], body["review_required_scene_total"], body["shared_scene_total"]) == (43, 36, 7, 25)
    assert [(row["cluster"], row["eligible_active_scene_count"], row["gap_to_target"]) for row in body["per_cluster"]] == [
        ("Automotive", 4, 0), ("Baby & Kids", 3, 0), ("Beauty", 6, 0),
        ("Electronics & Gadgets", 5, 0), ("Fashion", 3, 0), ("Food & Beverage", 9, 0),
        ("Home & Living", 10, 0), ("Islamic & Books", 3, 0), ("Office & Stationery", 7, 0),
        ("Pet Care", 3, 0), ("Sports & Outdoors", 5, 0), ("Tools & Home Improvement", 3, 0),
    ]
    assert body["registry_mutations"] == 0


def test_classification_api_hides_prompts_and_has_no_side_effect_contract():
    response = _client().get("/api/workspace/scene-context-registry/classification")
    assert response.status_code == 200
    body = response.json()
    assert body["active_scene_total"] == 43
    assert body["registry_mutations"] == 0
    assert len(body["scenes"]) == 43
    assert all("PromptV1" not in scene for scene in body["scenes"])
    assert all("prompt" not in scene for scene in body["scenes"])
    assert not {"sync", "provider_calls", "generation_jobs", "credits_used"} & set(body)
