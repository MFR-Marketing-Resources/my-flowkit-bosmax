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
        ProductIntelligenceReviewDraftApproveRequest(approved_by="op", claim_review_acknowledged=True),
    )
    return product["id"]


@pytest.mark.asyncio
async def test_expand_stages_a_review_required_draft_and_never_auto_approves():
    """Mission-08D contract: this lane was the LAST path able to mint an approved
    Product Intelligence snapshot without a human approval action. It now stages the
    expanded persona on a review-required draft and the snapshot must be untouched."""
    import json

    pid = await _product_with_snapshot("Angle Expand One", ["pain asal satu", "pain asal dua"])
    snap_before = await crud.get_latest_approved_product_intelligence_snapshot(pid)

    res = await svc.expand_product_angles(pid, ["pain baharu tiga", "pain baharu empat"])
    assert res["ok"] is True
    assert res["approved"] is False
    assert res["review_required"] is True
    assert res["added"] == 2
    assert res["angle_count"] == 4  # 2 original preserved + 2 new
    assert res["draft_id"]

    # THE assertion of the mission: no new snapshot version, persona in the approved
    # snapshot unchanged — approval only ever comes from the governed workflow.
    snap_after = await crud.get_latest_approved_product_intelligence_snapshot(pid)
    assert snap_after["snapshot_id"] == snap_before["snapshot_id"]
    assert snap_after["version"] == snap_before["version"]
    persona_snap = json.loads(snap_after["buyer_persona_snapshot_json"])
    assert "pain baharu tiga" not in (persona_snap.get("pains") or [])

    # The staged DRAFT carries all four pains and is review-required, not terminal.
    draft = await draft_svc.get_review_draft_by_id(res["draft_id"])
    assert draft.review_status not in draft_svc.TERMINAL_STATUSES
    pains = (draft.buyer_persona_snapshot_json or {}).get("pains") or []
    assert "pain asal satu" in pains and "pain baharu tiga" in pains


@pytest.mark.asyncio
async def test_expand_retry_updates_the_same_open_draft_no_duplicates():
    """Without auto-approval the staged draft stays OPEN; a retry must update it
    (one-open-draft rule) instead of erroring or duplicating."""
    pid = await _product_with_snapshot("Angle Expand Retry", ["pain asal satu"])
    first = await svc.expand_product_angles(pid, ["pain baharu dua"])
    second = await svc.expand_product_angles(pid, ["pain baharu tiga"])
    assert first["draft_id"] == second["draft_id"], "retry minted a second draft"
    drafts = await draft_svc.list_review_drafts(pid)
    open_drafts = [d for d in drafts.items
                   if d.review_status not in draft_svc.TERMINAL_STATUSES]
    assert len(open_drafts) == 1
    pains = (open_drafts[0].buyer_persona_snapshot_json or {}).get("pains") or []
    assert "pain baharu dua" in pains and "pain baharu tiga" in pains
    # and still: no snapshot growth
    snap = await crud.get_latest_approved_product_intelligence_snapshot(pid)
    assert snap["version"] == 1


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
    with pytest.raises(ValueError, match="COPY_INELIGIBLE|NO_APPROVED_SNAPSHOT|NO_ACCEPTED_SNAPSHOT"):
        await svc.expand_product_angles(product["id"], ["pain baharu"])


@pytest.mark.asyncio
async def test_expand_preserves_existing_open_draft_fields_and_authorship():
    pid = await _product_with_snapshot("Angle Preserve Open", ["approved pain"])
    request = _full_request(["draft-only pain"]).model_copy(update={
        "product_description": "Owner-edited open draft description.",
        "allowed_claims_json": ["owner-approved draft boundary"],
        "created_by": "manual-owner",
        "reviewer_note": "Preserve this owner note.",
    })
    open_draft = await draft_svc.create_review_draft(pid, request)

    result = await svc.expand_product_angles(pid, ["new staged pain"])
    assert result["draft_id"] == open_draft.draft_id
    refreshed = await draft_svc.get_review_draft_by_id(open_draft.draft_id)
    assert refreshed.product_description == "Owner-edited open draft description."
    assert refreshed.allowed_claims_json == ["owner-approved draft boundary"]
    assert refreshed.created_by == "manual-owner"
    assert "Preserve this owner note." in (refreshed.reviewer_note or "")
    assert "Angle expansion via Copy Components panel" in (
        refreshed.reviewer_note or "")
    assert "new staged pain" in (
        (refreshed.buyer_persona_snapshot_json or {}).get("pains") or [])
