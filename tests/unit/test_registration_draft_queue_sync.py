"""Editing a registration draft's evidence must re-sync the linked FastMoss queue
row's LIST status from the saved draft (never a HUB rebuild), so filling a field
clears its MISSING warning immediately and the operator edit is authoritative.
Regression: the langsir draft kept showing MISSING:SIZE_OR_VOLUME_EVIDENCE after
the field was filled because no save path touched the queue row.
"""
from types import SimpleNamespace

import pytest

from agent.db import crud
from agent.services.fastmoss_bulk_promotion_service import sync_queue_row_from_draft


def _draft(draft_id, missing, *, risk="LOW"):
    return SimpleNamespace(
        review_draft_id=draft_id,
        declared_evidence_fields={
            "product_name": "Langsir Kabinet",
            "image_url": "https://cdn.example/img.jpg",
            "tiktok_product_url": None,
        },
        claim_risk_level=risk,
        missing_required_evidence=list(missing),
        claim_tokens=[],
        claim_gate="CLAIM_SAFE",
    )


@pytest.mark.asyncio
async def test_sync_clears_missing_when_evidence_filled():
    ref, did = "fastmoss-ref:sync-1", "draft-sync-1"
    await crud.create_bulk_queue_row(
        ref, "Langsir Kabinet",
        promotion_status="MISSING_REQUIRED_FIELD",
        error_message="MISSING:SIZE_OR_VOLUME_EVIDENCE",
        recompute_state="BLOCKED_MISSING_EVIDENCE",
        draft_id=did, claim_risk_level="LOW", image_readiness="IMAGE_REFERENCE_READY",
    )
    updated = await sync_queue_row_from_draft(_draft(did, []))
    assert updated is not None
    assert updated["promotion_status"] != "MISSING_REQUIRED_FIELD"
    assert not updated["error_message"]
    assert updated["recompute_state"] == "UP_TO_DATE"


@pytest.mark.asyncio
async def test_sync_keeps_missing_when_still_missing():
    ref, did = "fastmoss-ref:sync-2", "draft-sync-2"
    await crud.create_bulk_queue_row(
        ref, "Langsir Kabinet 2",
        promotion_status="NEEDS_REVIEW",
        draft_id=did, claim_risk_level="LOW", image_readiness="IMAGE_REFERENCE_READY",
    )
    updated = await sync_queue_row_from_draft(_draft(did, ["SIZE_OR_VOLUME_EVIDENCE"]))
    assert updated["promotion_status"] == "MISSING_REQUIRED_FIELD"
    assert "SIZE_OR_VOLUME_EVIDENCE" in (updated["error_message"] or "")
    assert updated["recompute_state"] == "BLOCKED_MISSING_EVIDENCE"


@pytest.mark.asyncio
async def test_sync_noop_when_draft_has_no_queue_row():
    assert await sync_queue_row_from_draft(_draft("draft-unlinked", [])) is None
