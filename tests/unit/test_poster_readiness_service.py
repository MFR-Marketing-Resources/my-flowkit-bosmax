import pytest

from agent.models.poster_readiness import PosterReadinessStatus
from agent.services.poster_readiness_service import PosterReadinessService


def _ready_base(**overrides):
    product = {
        "id": "prod-ready-001",
        "raw_product_title": "Minyak Warisan Tok Cap Burung 25ml",
        "product_short_name": "Minyak Warisan",
        "product_display_name": "Minyak Warisan Tok Cap Burung 25ml",
        "lifecycle_status": "ACTIVE",
        "mapping_status": "READY",
        "category": "Health",
        "subcategory": "Herbal",
        "type": "Oil",
        "local_image_path": "data/product_images/prod-ready-001.jpg",
        "image_readiness_status": "IMAGE_CACHE_READY",
        "claim_risk_level": "MEDIUM",
        "claim_gate": "CLAIM_SAFE",
        "claim_safe_copy_status": "CLAIM_SAFE_COPY_APPROVED",
        "production_prompt_approval_status": "PRODUCTION_PROMPT_APPROVED",
        "production_prompt_approved_modes": '["IMG","T2V"]',
    }
    product.update(overrides)
    return product


@pytest.mark.asyncio
async def test_poster_ready_product():
    result = await PosterReadinessService.evaluate_product(_ready_base(), enrich=False)
    assert result.poster_status == PosterReadinessStatus.POSTER_READY
    assert result.generation_allowed is True
    assert result.production_allowed is True
    assert result.blockers == []
    assert result.image_tier.value == "PRODUCT_HERO_POSTER_READY"


@pytest.mark.asyncio
async def test_claim_risk_high_routes_to_repair_not_unrestricted_ready():
    product = _ready_base(
        id="bosmax-herbs-5ml",
        raw_product_title="Bosmax Herbs 5 ML",
        claim_risk_level="HIGH",
        claim_gate="CLAIM_REVIEW_REQUIRED",
        claim_safe_copy_status="CLAIM_SAFE_COPY_PREVIEW_ONLY",
    )
    result = await PosterReadinessService.evaluate_product(product, enrich=False)
    assert result.poster_status == PosterReadinessStatus.POSTER_REPAIR_REQUIRED
    assert result.generation_allowed is False
    assert result.production_allowed is False
    assert "CLAIM_RISK_HIGH" in result.blockers
    codes = [a.action_code for a in result.repair_actions]
    assert "RUN_SAFE_CLAIM_CLEARANCE" in codes
    assert "APPROVE_RESTRICTED_SAFE_POSTER_ROUTE" in codes
    assert result.claim_route.safe_claim_clearance_required is True


@pytest.mark.asyncio
async def test_bosmax_oil_same_as_herbs_high_risk():
    product = _ready_base(
        id="bosmax-oil-10ml",
        raw_product_title="Bosmax Oil 10 ML",
        claim_risk_level="HIGH",
    )
    result = await PosterReadinessService.evaluate_product(product, enrich=False)
    assert result.poster_status == PosterReadinessStatus.POSTER_REPAIR_REQUIRED
    assert "CLAIM_RISK_HIGH" in result.blockers


@pytest.mark.asyncio
async def test_restricted_ready_after_verified_clearance():
    product = _ready_base(
        claim_risk_level="MEDIUM",
        production_prompt_approval_note="Approved RESTRICTED_SAFE_POSTER route",
    )
    result = await PosterReadinessService.evaluate_product(product, enrich=False)
    assert result.poster_status == PosterReadinessStatus.POSTER_READY_RESTRICTED
    assert result.restricted_generation_required is True
    assert result.generation_allowed is True
    assert result.production_allowed is False


@pytest.mark.asyncio
async def test_mapping_missing_repair_required():
    product = _ready_base(mapping_status="MISSING", category="", subcategory="", type="")
    result = await PosterReadinessService.evaluate_product(product, enrich=False)
    assert result.poster_status == PosterReadinessStatus.POSTER_REPAIR_REQUIRED
    assert "MAPPING_MISSING" in result.blockers
    assert any(a.action_code == "RUN_PRODUCT_MAPPING" for a in result.repair_actions)


@pytest.mark.asyncio
async def test_img_not_prod_approved_repair():
    product = _ready_base(
        production_prompt_approval_status=None,
        production_prompt_approved_modes="[]",
    )
    result = await PosterReadinessService.evaluate_product(product, enrich=False)
    assert "IMG_NOT_PROD_APPROVED" in result.blockers
    assert any(a.action_code == "RUN_IMG_PRODUCTION_APPROVAL" for a in result.repair_actions)


@pytest.mark.asyncio
async def test_no_image_repair():
    product = _ready_base(
        local_image_path="",
        image_readiness_status="IMAGE_MISSING",
        asset_status="UNRESOLVED",
        image_url=None,
    )
    result = await PosterReadinessService.evaluate_product(product, enrich=False)
    assert "NO_IMAGE" in result.blockers
    assert any(a.action_code == "UPLOAD_PRODUCT_IMAGE" for a in result.repair_actions)


@pytest.mark.asyncio
async def test_archived_blocked():
    product = _ready_base(lifecycle_status="ARCHIVED")
    result = await PosterReadinessService.evaluate_product(product, enrich=False)
    assert result.poster_status == PosterReadinessStatus.POSTER_BLOCKED
    assert result.generation_allowed is False
    assert "PRODUCT_ARCHIVED" in result.blockers
    assert any(a.action_code == "UNARCHIVE_OR_DUPLICATE_PRODUCT" for a in result.repair_actions)


@pytest.mark.asyncio
async def test_every_listed_blocker_has_repair_action():
    from agent.services.poster_readiness_service import _repair_catalog

    catalog = _repair_catalog()
    for code, actions in catalog.items():
        assert actions, f"blocker {code} must map to actions"
        assert actions[0].action_code