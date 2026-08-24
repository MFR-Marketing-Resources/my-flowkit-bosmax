from types import SimpleNamespace

import pytest

from agent.db import crud
from agent.models.product_intelligence_review_draft import (
    ProductIntelligenceReviewDraftApproveRequest,
    ProductIntelligenceReviewDraftCreateRequest,
)
from agent.services import copy_angle_bulk_suggestion_service as svc
from agent.services import copy_angle_suggestion_service as sug_svc
from agent.services import product_intelligence_review_draft_service as draft_svc
from agent.services.copy_angle_derivation import MAX_ANGLES


def _full_request(pains):
    return ProductIntelligenceReviewDraftCreateRequest(
        product_description="Produk untuk ujian bulk.",
        benefits_json=["manfaat"],
        usp_json=["usp"],
        usage_text="Guna begini.",
        ingredients_text="Bahan.",
        warnings_text="Amaran.",
        target_customer_text="Sasaran.",
        allowed_claims_json=["selesa"],
        source_urls_json={"source_url": "https://example.com/s"},
        image_evidence_json={"image_url": "https://example.com/i.jpg"},
        buyer_persona_snapshot_json={"audience": "umum", "pains": pains},
        copy_strategy_summary_json={"angles": [], "market_problem_language": []},
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
    async def _fake_grounding(_product):
        return SimpleNamespace(is_stealth=False, family="", source="TEST")

    monkeypatch.setattr(sug_svc, "resolve_copy_grounding", _fake_grounding)


def _stub_provider(monkeypatch, payload):
    monkeypatch.setattr(sug_svc.provider, "complete_json", lambda system, user, **kwargs: payload)


@pytest.mark.asyncio
async def test_eligible_lists_only_products_with_room():
    pid_room = await _product_with_snapshot("Bulk Eligible Room", ["satu pain"])
    pid_full = await _product_with_snapshot(
        "Bulk Eligible Full", [f"pain {i}" for i in range(MAX_ANGLES)]  # 12 -> no room
    )
    res = await svc.list_eligible_products()
    ids = {item["product_id"] for item in res["items"]}
    assert pid_room in ids
    assert pid_full not in ids  # full -> excluded
    row = next(i for i in res["items"] if i["product_id"] == pid_room)
    assert row["angle_count"] == 1
    assert row["room"] == MAX_ANGLES - 1


@pytest.mark.asyncio
async def test_bulk_suggest_happy_path(monkeypatch):
    pid_a = await _product_with_snapshot("Bulk A", ["pain a"])
    pid_b = await _product_with_snapshot("Bulk B", ["pain b"])
    _stub_provider(monkeypatch, {"angles": ["angle baharu satu", "angle baharu dua"]})
    res = await svc.bulk_suggest([pid_a, pid_b])
    assert res["products"] == 2
    assert res["ok_products"] == 2
    assert res["total_suggestions"] == 4
    for r in res["results"]:
        assert r["ok"] is True
        assert r["suggestions"] == ["angle baharu satu", "angle baharu dua"]


@pytest.mark.asyncio
async def test_bulk_suggest_isolates_a_bad_product(monkeypatch):
    pid_ok = await _product_with_snapshot("Bulk OK", ["pain ok"])
    _stub_provider(monkeypatch, {"angles": ["angle ok"]})
    res = await svc.bulk_suggest([pid_ok, "does-not-exist"])
    by_id = {r["product_id"]: r for r in res["results"]}
    assert by_id[pid_ok]["ok"] is True
    assert by_id["does-not-exist"]["ok"] is False
    assert "PRODUCT_NOT_FOUND" in by_id["does-not-exist"]["error"]
    assert res["ok_products"] == 1  # one bad product never aborts the batch


@pytest.mark.asyncio
async def test_bulk_suggest_fails_fast_when_unconfigured(monkeypatch):
    pid = await _product_with_snapshot("Bulk Unconf", ["pain x"])

    def _boom(system, user, **kwargs):
        raise sug_svc.provider.AICopyProviderNotConfigured(
            sug_svc.provider.ERR_NOT_CONFIGURED
        )

    monkeypatch.setattr(sug_svc.provider, "complete_json", _boom)
    with pytest.raises(sug_svc.provider.AICopyProviderNotConfigured):
        await svc.bulk_suggest([pid])
