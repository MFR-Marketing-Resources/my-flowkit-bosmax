"""Shared copywriting readiness — composition logic per state (mocked reads)."""
import pytest

from agent.models.copy_grounding import (
    GROUNDING_APPROVED_SNAPSHOT,
    BuyerPersona,
    CopyGrounding,
    ProductKnowledge,
)
from agent.services import copywriting_readiness_service as svc


class _Snap:
    def __init__(self, status: str):
        self.status = status


def _grounding(is_stealth=False, benefits=None, audience="", pains=None, source=GROUNDING_APPROVED_SNAPSHOT):
    return CopyGrounding(
        product_id="p1",
        grounded=True,
        source=source,
        is_stealth=is_stealth,
        family="",
        product_knowledge=ProductKnowledge(
            benefits=list(benefits or []), usps=[], description=""
        ),
        buyer_persona=BuyerPersona(audience=audience, pains=list(pains or [])),
    )


def _wire(monkeypatch, *, snap_status, grounding, copy_rows):
    async def get_product(pid):
        return {"id": pid, "product_display_name": "P"}

    async def snap(pid):
        return _Snap(snap_status)

    async def ground(product):
        return grounding

    async def sets(pid):
        return copy_rows

    monkeypatch.setattr(svc.crud, "get_product", get_product)
    monkeypatch.setattr(svc, "get_latest_snapshot_response", snap)
    monkeypatch.setattr(svc, "resolve_copy_grounding", ground)
    monkeypatch.setattr(svc.crud, "list_copy_sets_for_product", sets)


@pytest.mark.asyncio
async def test_readiness_no_snapshot(monkeypatch):
    _wire(
        monkeypatch,
        snap_status="NO_APPROVED_SNAPSHOT",
        grounding=_grounding(source="FRAMEWORK_FAMILY"),
        copy_rows=[],
    )
    r = await svc.get_copywriting_readiness("p1")
    assert r["has_approved_snapshot"] is False
    assert r["ready_for_generation"] is False
    assert "NO_APPROVED_PRODUCT_INTELLIGENCE_SNAPSHOT" in r["blocking_reasons"]
    assert r["recommended_next_action"] == "PREPARE_PRODUCT_FOR_COPYWRITING"
    assert r["copy_applicable"] is True


@pytest.mark.asyncio
async def test_readiness_approved_snapshot_no_copy_set(monkeypatch):
    _wire(
        monkeypatch,
        snap_status="APPROVED_SNAPSHOT_AVAILABLE",
        grounding=_grounding(benefits=["b"], audience="ibu", pains=["anak kembung perut"]),
        copy_rows=[],
    )
    r = await svc.get_copywriting_readiness("p1")
    assert r["has_approved_snapshot"] is True
    assert r["product_knowledge_ready"] is True
    assert r["customer_avatar_ready"] is True
    assert r["approved_copy_set_count"] == 0
    assert "NO_APPROVED_COPY_SET" in r["blocking_reasons"]
    assert r["ready_for_generation"] is False
    assert r["recommended_next_action"] == "GENERATE_AND_APPROVE_COPY_SET"


@pytest.mark.asyncio
async def test_readiness_ready_with_approved_formula_copy(monkeypatch):
    row = {
        "copy_set_id": "cs1",
        "status": "COPY_APPROVED",
        "archived": 0,
        "usp_set_json": "[]",
        "claim_review_json": '{"formula_validation":{"valid":true,"review_required":false},"sales_clarity":{"clear":true}}',
    }
    _wire(
        monkeypatch,
        snap_status="APPROVED_SNAPSHOT_AVAILABLE",
        grounding=_grounding(benefits=["b"], audience="ibu", pains=["kembung perut"]),
        copy_rows=[row],
    )
    r = await svc.get_copywriting_readiness("p1")
    assert r["ready_for_generation"] is True
    assert r["approved_copy_set_count"] == 1
    assert r["selected_copy_set_id"] == "cs1"
    assert r["formula_validation_status"] == "PASS"
    assert r["sales_clarity_status"] == "CLEAR"
    assert r["recommended_next_action"] == "READY"
    assert r["blocking_reasons"] == []


@pytest.mark.asyncio
async def test_readiness_product_not_found(monkeypatch):
    from agent.services.copy_set_service import CopySetError

    async def none(pid):
        return None

    monkeypatch.setattr(svc.crud, "get_product", none)
    with pytest.raises(CopySetError) as exc:
        await svc.get_copywriting_readiness("missing")
    assert exc.value.code == "PRODUCT_NOT_FOUND"
