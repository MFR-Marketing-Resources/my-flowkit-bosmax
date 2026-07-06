from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.api.poster_readiness import router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def test_poster_readiness_endpoint_404(monkeypatch):
    async def fake_eval(_pid):
        return None

    monkeypatch.setattr(
        "agent.api.poster_readiness.PosterReadinessService.evaluate_product_id",
        fake_eval,
    )
    client = _client()
    response = client.get("/api/products/missing-id/poster-readiness")
    assert response.status_code == 404
    assert response.json()["detail"] == "PRODUCT_NOT_FOUND"


def test_poster_readiness_endpoint_contract(monkeypatch):
    from agent.models.poster_readiness import (
        PosterApprovalRoute,
        PosterClaimRoute,
        PosterImageTier,
        PosterMappingRoute,
        PosterReadinessResponse,
        PosterReadinessStatus,
        PosterRepairAction,
    )

    async def fake_eval(_pid):
        return PosterReadinessResponse(
            product_id="prod-1",
            product_display_name="Sample",
            poster_status=PosterReadinessStatus.POSTER_REPAIR_REQUIRED,
            preview_allowed=True,
            image_tier=PosterImageTier.PRODUCT_HERO_POSTER_READY,
            claim_route=PosterClaimRoute(claim_risk_level="HIGH", safe_claim_clearance_required=True),
            mapping_route=PosterMappingRoute(mapping_status="READY", mapping_ready=True),
            approval_route=PosterApprovalRoute(img_approved=False, approved_modes=[]),
            blockers=["CLAIM_RISK_HIGH"],
            repair_actions=[
                PosterRepairAction(
                    action_code="RUN_SAFE_CLAIM_CLEARANCE",
                    label="Run Safe Claim Clearance",
                    severity="P0",
                )
            ],
            next_best_action="RUN_SAFE_CLAIM_CLEARANCE",
        )

    monkeypatch.setattr(
        "agent.api.poster_readiness.PosterReadinessService.evaluate_product_id",
        fake_eval,
    )
    client = _client()
    response = client.get("/api/products/prod-1/poster-readiness")
    assert response.status_code == 200
    body = response.json()
    assert body["product_id"] == "prod-1"
    assert body["poster_status"] == "POSTER_REPAIR_REQUIRED"
    assert body["blockers"] == ["CLAIM_RISK_HIGH"]
    assert body["repair_actions"][0]["action_code"] == "RUN_SAFE_CLAIM_CLEARANCE"
    assert body["next_best_action"] == "RUN_SAFE_CLAIM_CLEARANCE"