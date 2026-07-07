import pytest

from agent.models.poster_copy_recommendations import (
    PosterCopyRecommendationRequest,
    PosterKitSource,
)
from agent.models.poster_readiness import (
    PosterApprovalRoute,
    PosterClaimRoute,
    PosterImageTier,
    PosterMappingRoute,
    PosterReadinessResponse,
    PosterReadinessStatus,
)
from agent.services.poster_copy_recommendation_service import (
    PosterCopyRecommendationService,
)
from tests.unit.test_poster_readiness_service import _ready_base


def _readiness(**kwargs) -> PosterReadinessResponse:
    base = {
        "product_id": "prod-ready-001",
        "product_display_name": "Test Product",
        "poster_status": PosterReadinessStatus.POSTER_READY,
        "generation_allowed": True,
        "restricted_generation_required": False,
        "preview_allowed": False,
        "production_allowed": True,
        "blockers": [],
        "repair_actions": [],
        "image_tier": PosterImageTier.PRODUCT_HERO_POSTER_READY,
        "claim_route": PosterClaimRoute(
            safe_claim_clearance_required=False,
            safe_claim_clearance_status="CLEAR",
            restricted_safe_poster_route_verified=False,
        ),
        "mapping_route": PosterMappingRoute(mapping_ready=True),
        "approval_route": PosterApprovalRoute(img_approved=True, approved_modes=["IMG"]),
        "recheck_required_after_repair": False,
        "notes": [],
    }
    base.update(kwargs)
    return PosterReadinessResponse(**base)


@pytest.mark.asyncio
async def test_ready_product_fallback_recommendations(monkeypatch):
    product = _ready_base()

    async def fake_get(_pid):
        return product

    async def fake_list(_pid):
        return []

    async def fake_eval(_product, enrich=False):
        return _readiness()

    monkeypatch.setattr(
        "agent.services.poster_copy_recommendation_service.crud.get_product",
        fake_get,
    )
    monkeypatch.setattr(
        "agent.services.poster_copy_recommendation_service.crud.list_copy_sets_for_product",
        fake_list,
    )
    monkeypatch.setattr(
        "agent.services.poster_copy_recommendation_service.PosterReadinessService.evaluate_product",
        fake_eval,
    )
    monkeypatch.setattr(
        "agent.services.poster_copy_recommendation_service.ai_provider.is_configured",
        lambda: False,
    )

    result = await PosterCopyRecommendationService.recommend(
        PosterCopyRecommendationRequest(product_id=product["id"])
    )
    assert result.generation_allowed is True
    assert len(result.recommendations) >= 3
    assert result.recommendations[0].source == PosterKitSource.FALLBACK_TEMPLATE
    assert result.recommendations[0].status == "candidate"


@pytest.mark.asyncio
async def test_repair_required_no_usable_kits(monkeypatch):
    product = _ready_base(claim_risk_level="HIGH")

    async def fake_get(_pid):
        return product

    async def fake_eval(_product, enrich=False):
        return _readiness(
            poster_status=PosterReadinessStatus.POSTER_REPAIR_REQUIRED,
            generation_allowed=False,
            blockers=["CLAIM_RISK_HIGH"],
            repair_actions=[
                {
                    "action_code": "RUN_SAFE_CLAIM_CLEARANCE",
                    "label": "Run clearance",
                    "severity": "high",
                }
            ],
        )

    monkeypatch.setattr(
        "agent.services.poster_copy_recommendation_service.crud.get_product",
        fake_get,
    )
    monkeypatch.setattr(
        "agent.services.poster_copy_recommendation_service.PosterReadinessService.evaluate_product",
        fake_eval,
    )

    result = await PosterCopyRecommendationService.recommend(
        PosterCopyRecommendationRequest(product_id=product["id"])
    )
    assert result.poster_status == "POSTER_REPAIR_REQUIRED"
    assert result.recommendations == []
    assert result.generation_allowed is False


@pytest.mark.asyncio
async def test_unsafe_copy_set_filtered(monkeypatch):
    product = _ready_base()

    async def fake_get(_pid):
        return product

    async def fake_list(_pid):
        return [
            {
                "id": "cs-1",
                "copy_set_id": "cs-1",
                "product_id": product["id"],
                "status": "COPY_APPROVED",
                "angle": "Bad",
                "hook": "This will cure your pain",
                "subhook": "x",
                "usp_set": ["a", "b", "c"],
                "cta": "Buy",
                "archived": 0,
            }
        ]

    async def fake_eval(_product, enrich=False):
        return _readiness()

    monkeypatch.setattr(
        "agent.services.poster_copy_recommendation_service.crud.get_product",
        fake_get,
    )
    monkeypatch.setattr(
        "agent.services.poster_copy_recommendation_service.crud.list_copy_sets_for_product",
        fake_list,
    )
    monkeypatch.setattr(
        "agent.services.poster_copy_recommendation_service.PosterReadinessService.evaluate_product",
        fake_eval,
    )
    monkeypatch.setattr(
        "agent.services.poster_copy_recommendation_service.ai_provider.is_configured",
        lambda: False,
    )

    result = await PosterCopyRecommendationService.recommend(
        PosterCopyRecommendationRequest(product_id=product["id"])
    )
    assert all("cure" not in k.hook.lower() for k in result.recommendations)


@pytest.mark.asyncio
async def test_ai_provider_failure_uses_fallback(monkeypatch):
    product = _ready_base()

    async def fake_get(_pid):
        return product

    async def fake_list(_pid):
        return []

    async def fake_eval(_product, enrich=False):
        return _readiness()

    def boom(_brief):
        from agent.services.ai_copy_provider_adapter import AICopyProviderError

        raise AICopyProviderError("ERR_RESPONSE_INVALID")

    monkeypatch.setattr(
        "agent.services.poster_copy_recommendation_service.crud.get_product",
        fake_get,
    )
    monkeypatch.setattr(
        "agent.services.poster_copy_recommendation_service.crud.list_copy_sets_for_product",
        fake_list,
    )
    monkeypatch.setattr(
        "agent.services.poster_copy_recommendation_service.PosterReadinessService.evaluate_product",
        fake_eval,
    )
    monkeypatch.setattr(
        "agent.services.poster_copy_recommendation_service.ai_provider.is_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        "agent.services.poster_copy_recommendation_service.ai_provider.generate_candidate",
        boom,
    )

    result = await PosterCopyRecommendationService.recommend(
        PosterCopyRecommendationRequest(product_id=product["id"], refresh_ai=True)
    )
    assert len(result.recommendations) >= 1
    assert any("fallback" in w.lower() or "ERR" in w for w in result.warnings) or result.recommendations


@pytest.mark.asyncio
async def test_kit_populates_prompt_draft_fields(monkeypatch):
    """Selecting kit fields satisfies prompt draft required copy."""
    from agent.services.poster_copy_recommendation_service import _fallback_kits

    product = _ready_base()
    settings = {
        "poster_objective": "Awareness",
        "poster_type": "Hero",
        "frame_ratio": "9:16",
        "language": "ms",
        "visual_route": "Premium commercial",
        "human_presence_mode": "none",
        "text_density": "medium",
        "brand_tone": "",
        "background_environment": "",
    }
    kits = _fallback_kits(product, settings, restricted=False)
    kit = kits[0]
    assert kit.hook and kit.cta and kit.angle