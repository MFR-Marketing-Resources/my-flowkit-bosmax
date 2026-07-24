import pytest

from agent.db import crud
from agent.models.product_intelligence_review_draft import (
    ProductIntelligenceReviewDraftApproveRequest,
    ProductIntelligenceReviewDraftCreateRequest,
)
from agent.services import product_intelligence_review_draft_service as draft_svc
from agent.services import copy_angle_expansion_service as svc
from agent.services.copy_angle_derivation import MAX_ANGLES


def _full_request(pains):
    # Every required field present + a clean persona -> CLAIM_SAFE, approvable.
    return ProductIntelligenceReviewDraftCreateRequest(
        product_description="Minyak urut tradisional untuk kegunaan luaran.",
        benefits_json=["melegakan badan"],
        usp_json=["resepi warisan"],
        usage_text="Sapu pada bahagian yang berkenaan.",
        ingredients_text="Campuran herba tradisional.",
        warnings_text="Untuk kegunaan luaran sahaja.",
        target_customer_text="Individu dewasa.",
        allowed_claims_json=["melegakan ketidakselesaan"],
        source_urls_json={"source_url": "https://example.com/s"},
        image_evidence_json={"image_url": "https://example.com/i.jpg"},
        buyer_persona_snapshot_json={"audience": "dewasa", "pains": pains},
        copy_strategy_summary_json={"angles": []},
        created_by="op",
    )


async def _product_with_snapshot(name, pains):
    product = await crud.create_product(
        raw_product_title=name, source="MANUAL", product_display_name=name,
    )
    draft = await draft_svc.create_review_draft(product["id"], _full_request(pains))
    await draft_svc.approve_review_draft(
        draft.draft_id,
        ProductIntelligenceReviewDraftApproveRequest(approved_by="op"),
    )
    return product["id"]


@pytest.mark.asyncio
async def test_expand_appends_angles_and_preserves_existing():
    pid = await _product_with_snapshot("Angle Expand One", ["pain asal satu", "pain asal dua"])
    res = await svc.expand_product_angles(pid, ["pain baharu tiga", "pain baharu empat"])
    assert res["ok"] is True
    assert res["added"] == 2
    assert res["angle_count"] == 4  # 2 original preserved + 2 new
    # the new snapshot's persona carries all four pains
    snap = await crud.get_latest_approved_product_intelligence_snapshot(pid)
    import json
    persona = json.loads(snap["buyer_persona_snapshot_json"])
    assert "pain asal satu" in persona["pains"] and "pain baharu tiga" in persona["pains"]


@pytest.mark.asyncio
async def test_expand_dedupes_existing_pain():
    pid = await _product_with_snapshot("Angle Expand Dedupe", ["pain asal satu"])
    res = await svc.expand_product_angles(pid, ["Pain Asal Satu", "pain betul betul baharu"])
    assert res["added"] == 1  # the duplicate (case-insensitive) is dropped
    assert res["angle_count"] == 2


@pytest.mark.asyncio
async def test_expand_caps_at_max_angles():
    start = [f"pain asal nombor {i}" for i in range(MAX_ANGLES - 2)]  # 10
    pid = await _product_with_snapshot("Angle Expand Cap", start)
    res = await svc.expand_product_angles(pid, [f"pain tambahan {i}" for i in range(5)])
    assert res["ok"] is True
    assert res["capped"] is True
    assert res["angle_count"] == MAX_ANGLES  # 12
    assert res["added"] == 2  # only room for 2 more


@pytest.mark.asyncio
async def test_expand_requires_pains():
    pid = await _product_with_snapshot("Angle Expand Empty", ["pain asal"])
    with pytest.raises(ValueError, match="NO_PAINS_PROVIDED"):
        await svc.expand_product_angles(pid, ["   ", ""])


@pytest.mark.asyncio
async def test_expand_without_snapshot_raises():
    product = await crud.create_product(
        raw_product_title="No Snapshot Product", source="MANUAL",
        product_display_name="No Snapshot Product",
    )
    with pytest.raises(ValueError, match="NO_APPROVED_SNAPSHOT"):
        await svc.expand_product_angles(product["id"], ["pain baharu"])
