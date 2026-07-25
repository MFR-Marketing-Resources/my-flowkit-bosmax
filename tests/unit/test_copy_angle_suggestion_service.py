from types import SimpleNamespace

import pytest

from agent.db import crud
from agent.models.product_intelligence_review_draft import (
    ProductIntelligenceReviewDraftApproveRequest,
    ProductIntelligenceReviewDraftCreateRequest,
)
from agent.services import copy_angle_suggestion_service as svc
from agent.services import product_intelligence_review_draft_service as draft_svc
from agent.services.copy_angle_derivation import MAX_ANGLES


def _full_request(pains):
    # Every required field present + a clean persona -> CLAIM_SAFE, approvable.
    return ProductIntelligenceReviewDraftCreateRequest(
        product_description="Lampin seluar untuk bayi aktif.",
        benefits_json=["serap tinggi"],
        usp_json=["seluar tarik mudah pakai"],
        usage_text="Pakai dan tanggalkan seperti seluar.",
        ingredients_text="Bahan serap.",
        warnings_text="Tukar dengan kerap.",
        target_customer_text="Ibu bapa bayi.",
        allowed_claims_json=["selesa dipakai"],
        source_urls_json={"source_url": "https://example.com/s"},
        image_evidence_json={"image_url": "https://example.com/i.jpg"},
        buyer_persona_snapshot_json={"audience": "ibu bapa", "pains": pains},
        copy_strategy_summary_json={
            "angles": [],
            "market_problem_language": ["lampin bocor"],
        },
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


@pytest.fixture(autouse=True)
def _stub_grounding(monkeypatch):
    # Keep the unit isolated: grounding only supplies is_stealth to the prompt.
    async def _fake_grounding(_product):
        return SimpleNamespace(is_stealth=False, family="", source="TEST")

    monkeypatch.setattr(svc, "resolve_copy_grounding", _fake_grounding)


def _stub_provider(monkeypatch, payload):
    monkeypatch.setattr(svc.provider, "complete_json", lambda system, user: payload)


@pytest.mark.asyncio
async def test_suggest_returns_new_angles(monkeypatch):
    pid = await _product_with_snapshot("Suggest One", ["lampin bocor waktu malam"])
    _stub_provider(monkeypatch, {"angles": ["kulit bayi merah", "susah pakai bila meronta"]})
    res = await svc.suggest_product_angles(pid, count=8)
    assert res["ok"] is True
    assert res["suggestions"] == ["kulit bayi merah", "susah pakai bila meronta"]
    assert res["existing_count"] == 1
    assert res["warnings"] == []


@pytest.mark.asyncio
async def test_suggest_dedupes_existing_pain(monkeypatch):
    pid = await _product_with_snapshot("Suggest Dedupe", ["lampin bocor waktu malam"])
    # The first candidate re-words the existing pain (different case) -> dropped.
    _stub_provider(monkeypatch, {"angles": ["Lampin Bocor Waktu Malam", "kembung perut bayi"]})
    res = await svc.suggest_product_angles(pid)
    assert res["suggestions"] == ["kembung perut bayi"]


@pytest.mark.asyncio
async def test_suggest_caps_to_remaining_slots(monkeypatch):
    start = [f"pain sedia ada {i}" for i in range(MAX_ANGLES - 2)]  # 10 -> 2 slots left
    pid = await _product_with_snapshot("Suggest Cap", start)
    _stub_provider(monkeypatch, {"angles": [f"pain baharu {i}" for i in range(6)]})
    res = await svc.suggest_product_angles(pid, count=8)
    assert res["remaining_slots"] == 2
    assert len(res["suggestions"]) == 2


@pytest.mark.asyncio
async def test_suggest_accepts_pains_key(monkeypatch):
    pid = await _product_with_snapshot("Suggest Pains Key", ["pain a"])
    _stub_provider(monkeypatch, {"pains": ["pain b"]})  # tolerate the alt key
    res = await svc.suggest_product_angles(pid)
    assert res["suggestions"] == ["pain b"]


@pytest.mark.asyncio
async def test_suggest_empty_output_warns(monkeypatch):
    pid = await _product_with_snapshot("Suggest Empty", ["pain a"])
    _stub_provider(monkeypatch, {"angles": []})
    res = await svc.suggest_product_angles(pid)
    assert res["ok"] is True
    assert res["suggestions"] == []
    assert "NO_SUGGESTIONS" in res["warnings"]


@pytest.mark.asyncio
async def test_suggest_without_snapshot_raises(monkeypatch):
    product = await crud.create_product(
        raw_product_title="Suggest No Snap", source="MANUAL",
        product_display_name="Suggest No Snap",
    )
    _stub_provider(monkeypatch, {"angles": ["x"]})
    with pytest.raises(ValueError, match="NO_APPROVED_SNAPSHOT"):
        await svc.suggest_product_angles(product["id"])


@pytest.mark.asyncio
async def test_suggest_missing_product_raises(monkeypatch):
    _stub_provider(monkeypatch, {"angles": ["x"]})
    with pytest.raises(ValueError, match="PRODUCT_NOT_FOUND"):
        await svc.suggest_product_angles("does-not-exist")


@pytest.mark.asyncio
async def test_suggest_propagates_not_configured(monkeypatch):
    pid = await _product_with_snapshot("Suggest Unconf", ["pain a"])

    def _boom(system, user):
        raise svc.provider.AICopyProviderNotConfigured(svc.provider.ERR_NOT_CONFIGURED)

    monkeypatch.setattr(svc.provider, "complete_json", _boom)
    with pytest.raises(svc.provider.AICopyProviderNotConfigured):
        await svc.suggest_product_angles(pid)
