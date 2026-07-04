"""The Product Asset Generator preview must not answer with a generic
PRODUCT_NOT_FOUND for pipeline ids. If the selector can list an option, the
backend preview must be able to EXPLAIN why it cannot resolve — reference-only
vs not-yet-canonical vs truly unknown."""

from agent.db import crud
from agent.services import product_asset_generator_service as svc


def _req(product_id):
    return {
        "product_id": product_id,
        "target_asset_intent": "CHARACTER_CONCEPT",
        "dry_run_only": True,
    }


async def test_reference_only_id_gets_state_aware_preview_error(monkeypatch):
    async def fake_get_product(pid):
        return None

    async def fake_get_bulk_queue_row(rid):
        return None

    async def fake_refs(limit=500):
        return [{"id": "fastmoss-ref:preview1", "source": "FASTMOSS",
                 "source_lane": "FASTMOSS_REFERENCE", "reference_only": True}]

    monkeypatch.setattr("agent.db.crud.get_product", fake_get_product)
    monkeypatch.setattr("agent.db.crud.get_bulk_queue_row", fake_get_bulk_queue_row)
    monkeypatch.setattr(
        "agent.services.fastmoss_product_reference_service.list_fastmoss_reference_products",
        fake_refs,
    )

    resp = await svc.generate_product_asset_preview(_req("fastmoss-ref:preview1"))

    assert resp.preview_status == "FAIL"
    assert "REFERENCE_ONLY_PREVIEW_REQUIRES_REGISTRATION" in resp.errors
    assert "PRODUCT_NOT_FOUND" not in resp.errors


async def test_ready_for_approval_id_reports_not_yet_canonical(monkeypatch):
    async def fake_get_product(pid):
        return None

    async def fake_get_bulk_queue_row(rid):
        return {
            "reference_id": rid,
            "promotion_status": "READY_FOR_APPROVAL",
            "draft_id": "draft-x",
            "committed_product_id": None,
        }

    monkeypatch.setattr("agent.db.crud.get_product", fake_get_product)
    monkeypatch.setattr("agent.db.crud.get_bulk_queue_row", fake_get_bulk_queue_row)

    resp = await svc.generate_product_asset_preview(_req("fastmoss-ref:preview2"))

    assert resp.preview_status == "FAIL"
    assert "PRODUCT_NOT_YET_CANONICAL" in resp.errors


async def test_truly_unknown_id_still_reports_product_not_found(monkeypatch):
    async def none_(*a, **k):
        return None

    async def empty(*a, **k):
        return []

    monkeypatch.setattr("agent.db.crud.get_product", none_)
    monkeypatch.setattr("agent.db.crud.get_bulk_queue_row", none_)
    monkeypatch.setattr(
        "agent.services.fastmoss_product_reference_service.list_fastmoss_reference_products",
        empty,
    )

    resp = await svc.generate_product_asset_preview(_req("ghost-id"))

    assert resp.preview_status == "FAIL"
    assert "PRODUCT_NOT_FOUND" in resp.errors
