"""Locks the Product Truth Gateway / ProductCatalogReadModel join states.

Every assertion here defends one broken join the wiring audit found:
reference-only must never masquerade as canonical, READY_FOR_APPROVAL stays
preview-only, APPROVED links a committed canonical product, and unknown ids fail
closed instead of resolving to a fake product.
"""

import pytest

from agent.db import crud
from agent.services import product_catalog_read_model as prm


async def _seed_queue(reference_id, **kw):
    await crud.create_bulk_queue_row(reference_id, kw.pop("title", "Ref Row"))
    if kw:
        await crud.update_bulk_queue_row(reference_id, **kw)
    return await crud.get_bulk_queue_row(reference_id)


def _patch_reference(monkeypatch, rows):
    async def _fake_list(limit=500):
        return rows[:limit]

    monkeypatch.setattr(
        "agent.services.fastmoss_product_reference_service.list_fastmoss_reference_products",
        _fake_list,
    )


@pytest.mark.asyncio
async def test_reference_only_row_resolves_as_reference_only(monkeypatch):
    ref = {
        "id": "fastmoss-ref:aaa111",
        "product_id": None,
        "source": "FASTMOSS",
        "source_lane": "FASTMOSS_REFERENCE",
        "reference_only": True,
        "category": "BEAUTY",
        "claim_risk_level": "LOW",
    }
    _patch_reference(monkeypatch, [ref])

    view = await prm.resolve_product_state("fastmoss-ref:aaa111")

    assert view["product_state"] == prm.PRODUCT_STATE_REFERENCE_ONLY
    assert view["reference_only"] is True
    assert view["canonical_status"] == prm.CANONICAL_STATUS_NOT_CANONICAL
    assert view["product_id"] is None
    assert view["reference_id"] == "fastmoss-ref:aaa111"


@pytest.mark.asyncio
async def test_reference_only_cannot_be_production_generated(monkeypatch):
    ref = {"id": "fastmoss-ref:bbb222", "source": "FASTMOSS",
           "source_lane": "FASTMOSS_REFERENCE", "reference_only": True}
    _patch_reference(monkeypatch, [ref])

    view = await prm.resolve_product_state("fastmoss-ref:bbb222")

    assert view["production_allowed"] is False
    assert view["preview_resolvable"] is False  # crud.get_product cannot resolve it
    assert view["blocked_reason"] == "REFERENCE_ONLY_REQUIRES_REGISTRATION"


@pytest.mark.asyncio
async def test_ready_for_approval_is_preview_only():
    await _seed_queue(
        "fastmoss-ref:ccc333",
        promotion_status="READY_FOR_APPROVAL",
        draft_id="draft-ccc",
    )

    view = await prm.resolve_product_state("fastmoss-ref:ccc333")

    assert view["product_state"] == prm.PRODUCT_STATE_READY_FOR_APPROVAL
    assert view["preview_allowed"] is True
    assert view["production_allowed"] is False
    assert view["draft_id"] == "draft-ccc"
    assert view["committed_product_id"] is None


@pytest.mark.asyncio
async def test_claim_risk_queue_row_is_blocked():
    await _seed_queue("fastmoss-ref:ddd444", promotion_status="CLAIM_RISK")
    view = await prm.resolve_product_state("fastmoss-ref:ddd444")
    assert view["product_state"] == prm.PRODUCT_STATE_BLOCKED_CLAIM_RISK
    assert view["production_allowed"] is False
    assert view["blocked_reason"] == "QUEUE_STATUS_CLAIM_RISK"


@pytest.mark.asyncio
async def test_missing_required_field_queue_row_is_blocked():
    await _seed_queue("fastmoss-ref:eee555", promotion_status="MISSING_REQUIRED_FIELD")
    view = await prm.resolve_product_state("fastmoss-ref:eee555")
    assert view["product_state"] == prm.PRODUCT_STATE_BLOCKED_MISSING_REQUIRED_FIELD
    assert view["production_allowed"] is False


@pytest.mark.asyncio
async def test_approved_row_links_committed_canonical_product():
    product = await crud.create_product(
        "Committed Widget",
        source="MANUAL",
        product_display_name="Committed Widget",
        product_short_name="Committed Widget",
        mapping_source="FASTMOSS_PROMOTED",
        fastmoss_reference_id="fastmoss-ref:fff666",
        claim_risk_level="LOW",
    )
    await _seed_queue(
        "fastmoss-ref:fff666",
        promotion_status="APPROVED",
        draft_id="draft-fff",
        committed_product_id=product["id"],
    )

    view = await prm.resolve_product_state("fastmoss-ref:fff666")

    assert view["product_state"] == prm.PRODUCT_STATE_APPROVED_CANONICAL
    assert view["canonical_status"] == prm.CANONICAL_STATUS_CANONICAL
    assert view["product_id"] == product["id"]
    assert view["committed_product_id"] == product["id"]
    assert view["reference_id"] == "fastmoss-ref:fff666"
    assert view["production_allowed"] is True
    assert view["preview_resolvable"] is True


@pytest.mark.asyncio
async def test_canonical_product_looked_up_by_uuid_reexposes_reference_lineage():
    product = await crud.create_product(
        "Direct Widget",
        source="MANUAL",
        product_display_name="Direct Widget",
        product_short_name="Direct Widget",
        fastmoss_reference_id="fastmoss-ref:ggg777",
    )
    view = await prm.resolve_product_state(product["id"])
    assert view["product_state"] == prm.PRODUCT_STATE_APPROVED_CANONICAL
    assert view["reference_id"] == "fastmoss-ref:ggg777"
    assert view["product_id"] == product["id"]


@pytest.mark.asyncio
async def test_approved_but_committed_product_absent_is_runtime_storage_unverified():
    # Queue says APPROVED with a committed id, but that product row is not in the
    # active storage — the exact cross-worktree binding split the audit flagged.
    await _seed_queue(
        "fastmoss-ref:hhh888",
        promotion_status="APPROVED",
        committed_product_id="missing-uuid-not-in-db",
    )
    view = await prm.resolve_product_state("fastmoss-ref:hhh888")
    assert view["product_state"] == prm.PRODUCT_STATE_RUNTIME_STORAGE_UNVERIFIED
    assert view["committed_product_id"] == "missing-uuid-not-in-db"
    assert view["production_allowed"] is False


@pytest.mark.asyncio
async def test_unknown_identifier_fails_closed(monkeypatch):
    _patch_reference(monkeypatch, [])
    view = await prm.resolve_product_state("totally-unknown-id")
    assert view["product_state"] == prm.PRODUCT_STATE_CONTEXT_NOT_FOUND
    assert view["product_id"] is None
    assert view["production_allowed"] is False


@pytest.mark.asyncio
async def test_duplicate_linked_with_resolvable_linked_product():
    linked = await crud.create_product(
        "Existing Truth",
        source="MANUAL",
        product_display_name="Existing Truth",
        product_short_name="Existing Truth",
        claim_risk_level="LOW",
    )
    await _seed_queue(
        "fastmoss-ref:dup111",
        promotion_status="DUPLICATE_LINKED",
        linked_product_id=linked["id"],
    )
    view = await prm.resolve_product_state(
        "fastmoss-ref:dup111", authority_ids={linked["id"]}
    )
    assert view["product_state"] == prm.PRODUCT_STATE_DUPLICATE_LINKED
    assert view["linked_product_id"] == linked["id"]
    assert view["product_id"] == linked["id"]
    assert view["canonical_status"] == prm.CANONICAL_STATUS_CANONICAL
    assert view["production_allowed"] is True  # existing FastMoss policy: use linked truth
    assert view["preview_resolvable"] is True
    assert view["authority_context_available"] is True
    assert view["blocked_reason"] is None


@pytest.mark.asyncio
async def test_duplicate_linked_with_missing_linked_product():
    await _seed_queue(
        "fastmoss-ref:dup222",
        promotion_status="DUPLICATE_LINKED",
        linked_product_id="ghost-linked-uuid",
    )
    view = await prm.resolve_product_state("fastmoss-ref:dup222")
    assert view["product_state"] == prm.PRODUCT_STATE_RUNTIME_STORAGE_UNVERIFIED
    assert view["linked_product_id"] == "ghost-linked-uuid"
    assert view["blocked_reason"] == "LINKED_PRODUCT_NOT_IN_ACTIVE_STORAGE"
    assert view["production_allowed"] is False


@pytest.mark.asyncio
async def test_duplicate_linked_without_linked_product_id():
    await _seed_queue("fastmoss-ref:dup333", promotion_status="DUPLICATE_LINKED")
    view = await prm.resolve_product_state("fastmoss-ref:dup333")
    assert view["product_state"] == prm.PRODUCT_STATE_DUPLICATE_LINKED
    assert view["blocked_reason"] == "DUPLICATE_LINK_UNRESOLVED"
    assert view["production_allowed"] is False


@pytest.mark.asyncio
async def test_reference_id_resolves_to_canonical_when_queue_missing(monkeypatch):
    # No queue row for this reference, but a committed canonical product carries
    # its fastmoss_reference_id — the canonical row must win (audit HOLD item C).
    _patch_reference(monkeypatch, [{"id": "fastmoss-ref:iii999", "reference_only": True}])
    product = await crud.create_product(
        "Committed Via Ref",
        source="MANUAL",
        product_display_name="Committed Via Ref",
        product_short_name="Committed Via Ref",
        fastmoss_reference_id="fastmoss-ref:iii999",
    )
    view = await prm.resolve_product_state("fastmoss-ref:iii999")
    assert view["product_state"] == prm.PRODUCT_STATE_APPROVED_CANONICAL
    assert view["product_id"] == product["id"]
    assert view["reference_id"] == "fastmoss-ref:iii999"
    assert view["canonical_status"] == prm.CANONICAL_STATUS_CANONICAL


def test_derive_catalog_state_reference_row():
    state = prm.derive_catalog_state(
        {"id": "fastmoss-ref:x", "reference_only": True}
    )
    assert state["product_state"] == prm.PRODUCT_STATE_REFERENCE_ONLY
    assert state["production_allowed"] is False
    assert state["preview_resolvable"] is False


def test_derive_catalog_state_canonical_row():
    state = prm.derive_catalog_state(
        {"id": "prod-1", "reference_only": False, "fastmoss_reference_id": "fastmoss-ref:y"}
    )
    assert state["product_state"] == prm.PRODUCT_STATE_APPROVED_CANONICAL
    assert state["canonical_status"] == prm.CANONICAL_STATUS_CANONICAL
    assert state["product_id"] == "prod-1"
    assert state["reference_id"] == "fastmoss-ref:y"


@pytest.mark.asyncio
async def test_authority_context_available_tracks_authority_id_set():
    # Within one bound storage, authority (which iterates the product table) and
    # the read model cannot silently disagree: a canonical product present in the
    # authority id set reports authority_context_available True; absence -> False.
    product = await crud.create_product(
        "Authority Widget",
        source="MANUAL",
        product_display_name="Authority Widget",
        product_short_name="Authority Widget",
    )
    seen = await prm.resolve_product_state(product["id"], authority_ids={product["id"]})
    assert seen["authority_context_available"] is True

    hidden = await prm.resolve_product_state(product["id"], authority_ids=set())
    assert hidden["authority_context_available"] is False
