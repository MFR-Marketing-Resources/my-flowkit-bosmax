from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.poster_prompt import router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def test_copy_recommendations_repair_required(monkeypatch):
    async def fake_recommend(_req):
        from agent.models.poster_copy_recommendations import (
            PosterCopyRecommendationsResponse,
        )

        return PosterCopyRecommendationsResponse(
            product_id="p1",
            poster_status="POSTER_REPAIR_REQUIRED",
            generation_allowed=False,
            recommendations=[],
            repair_actions=[{"action_code": "RUN_SAFE_CLAIM_CLEARANCE"}],
        )

    monkeypatch.setattr(
        "agent.api.poster_prompt.PosterCopyRecommendationService.recommend",
        fake_recommend,
    )
    response = _client().post(
        "/api/poster/copy-recommendations",
        json={"product_id": "p1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["poster_status"] == "POSTER_REPAIR_REQUIRED"
    assert body["recommendations"] == []


def test_copy_recommendations_ready_shape(monkeypatch):
    async def fake_recommend(_req):
        from agent.models.poster_copy_recommendations import (
            PosterCopyKit,
            PosterCopyRecommendationsResponse,
            PosterKitSource,
            PosterKitStatus,
        )

        return PosterCopyRecommendationsResponse(
            product_id="p1",
            poster_status="POSTER_READY",
            generation_allowed=True,
            recommendation_source=PosterKitSource.FALLBACK_TEMPLATE,
            recommendations=[
                PosterCopyKit(
                    kit_id="k1",
                    status=PosterKitStatus.CANDIDATE,
                    source=PosterKitSource.FALLBACK_TEMPLATE,
                    angle="Trust",
                    hook="Safe hook",
                    cta="Shop",
                )
            ],
        )

    monkeypatch.setattr(
        "agent.api.poster_prompt.PosterCopyRecommendationService.recommend",
        fake_recommend,
    )
    response = _client().post(
        "/api/poster/copy-recommendations",
        json={"product_id": "p1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["recommendations"]) == 1
    assert body["recommendations"][0]["source"] == "FALLBACK_TEMPLATE"